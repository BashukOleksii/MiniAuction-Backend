import re
from datetime import datetime

from pydantic import ValidationError

from app.models.auction import Auction, AuctionStatus
from app.models.common import utc_now
from app.models.user import User
from app.repositories.auction_repository import AuctionRepository
from app.schemas.auction import (
    AuctionCreateRequest,
    AuctionPage,
    AuctionResponse,
    AuctionUpdateRequest,
    PublicAuctionFilter,
)


class AuctionNotFoundError(Exception):
    pass


class AuctionForbiddenError(Exception):
    pass


class AuctionConflictError(Exception):
    pass


class AuctionDataError(Exception):
    pass


def effective_status(auction: Auction, now: datetime) -> str:
    status = auction.status.value if isinstance(auction.status, AuctionStatus) else auction.status
    if status != AuctionStatus.ACTIVE.value:
        return status
    if now < auction.starts_at:
        return "scheduled"
    if now >= auction.ends_at:
        return "finished"
    return "active"


def auction_response(auction: Auction, now: datetime) -> AuctionResponse:
    return AuctionResponse.model_validate(
        {**auction.model_dump(mode="python"), "effective_status": effective_status(auction, now)}
    )


def public_query(
    now: datetime,
    availability: PublicAuctionFilter,
    search: str | None,
    category: str | None,
    min_price: int | None,
    max_price: int | None,
) -> dict:
    if availability == "active":
        query: dict = {
            "status": AuctionStatus.ACTIVE.value,
            "starts_at": {"$lte": now},
            "ends_at": {"$gt": now},
        }
    elif availability == "scheduled":
        query = {"status": AuctionStatus.ACTIVE.value, "starts_at": {"$gt": now}}
    else:
        query = {
            "$or": [
                {"status": AuctionStatus.FINISHED.value},
                {"status": AuctionStatus.ACTIVE.value, "ends_at": {"$lte": now}},
            ]
        }

    if category:
        query["category"] = category.strip().lower()
    price: dict = {}
    if min_price is not None:
        price["$gte"] = min_price
    if max_price is not None:
        price["$lte"] = max_price
    if price:
        query["current_price"] = price
    if search and search.strip():
        safe_search = re.escape(search.strip())
        query["$and"] = [
            {"$or": [
                {"title": {"$regex": safe_search, "$options": "i"}},
                {"description": {"$regex": safe_search, "$options": "i"}},
            ]}
        ]
    return query


class AuctionService:
    def __init__(self, repository: AuctionRepository):
        self.repository = repository

    async def create(self, data: AuctionCreateRequest, owner: User) -> Auction:
        now = utc_now()
        starts_at = data.starts_at or now
        if data.ends_at <= now or data.ends_at <= starts_at:
            raise AuctionDataError("Auction end time must be in the future and after start")
        auction = Auction(
            seller_id=owner.id,
            title=data.title,
            description=data.description,
            category=data.category,
            starting_price=data.starting_price,
            current_price=data.starting_price,
            min_bid_step=data.min_bid_step,
            starts_at=starts_at,
            ends_at=data.ends_at,
            status=AuctionStatus.DRAFT,
        )
        return await self.repository.create(auction)

    async def get(self, auction_id: str, viewer: User | None = None) -> Auction:
        auction = await self.repository.get_by_id(auction_id)
        if auction is None:
            raise AuctionNotFoundError
        if auction.status == AuctionStatus.DRAFT.value and (
            viewer is None or (viewer.id != auction.seller_id and viewer.role != "admin")
        ):
            raise AuctionNotFoundError
        return auction

    @staticmethod
    def require_owner(auction: Auction, user: User) -> None:
        if auction.seller_id != user.id:
            raise AuctionForbiddenError

    async def update(self, auction_id: str, data: AuctionUpdateRequest, owner: User) -> Auction:
        auction = await self.repository.get_by_id(auction_id)
        if auction is None:
            raise AuctionNotFoundError
        self.require_owner(auction, owner)
        if auction.status != AuctionStatus.DRAFT.value:
            raise AuctionConflictError("Only drafts can be edited")

        changes = data.model_dump(exclude_unset=True, mode="python")
        if "starting_price" in changes:
            changes["current_price"] = changes["starting_price"]
        try:
            proposed = Auction.model_validate(
                {**auction.model_dump(mode="python"), **changes}
            )
        except ValidationError as exc:
            raise AuctionDataError("Invalid price or date combination") from exc
        if proposed.ends_at <= utc_now():
            raise AuctionDataError("Auction must end in the future")
        updated = await self.repository.update_draft(auction_id, owner.id, changes)
        if updated is None:
            raise AuctionConflictError("Auction changed concurrently")
        return updated

    async def publish(self, auction_id: str, owner: User) -> Auction:
        auction = await self.repository.get_by_id(auction_id)
        if auction is None:
            raise AuctionNotFoundError
        self.require_owner(auction, owner)
        if auction.status != AuctionStatus.DRAFT.value:
            raise AuctionConflictError("Only drafts can be published")
        now = utc_now()
        if auction.ends_at <= now:
            raise AuctionConflictError("Auction has already expired")
        published = await self.repository.publish(auction_id, owner.id, now)
        if published is None:
            raise AuctionConflictError("Auction changed concurrently")
        return published

    async def cancel(self, auction_id: str, owner: User) -> Auction:
        auction = await self.repository.get_by_id(auction_id)
        if auction is None:
            raise AuctionNotFoundError
        self.require_owner(auction, owner)
        if auction.status not in (AuctionStatus.DRAFT.value, AuctionStatus.ACTIVE.value):
            raise AuctionConflictError("Auction cannot be cancelled in this state")
        now = utc_now()
        if auction.status == AuctionStatus.ACTIVE.value and auction.ends_at <= now:
            raise AuctionConflictError("Finished auction cannot be cancelled")
        if auction.leader_id is not None or auction.current_price != auction.starting_price:
            raise AuctionConflictError("Auction with bids cannot be cancelled")
        cancelled = await self.repository.cancel(
            auction_id, owner.id, auction.status, auction.current_price, now
        )
        if cancelled is None:
            raise AuctionConflictError("Auction changed concurrently or has a bid")
        return cancelled

    async def list_public(
        self,
        *,
        availability: PublicAuctionFilter,
        search: str | None,
        category: str | None,
        min_price: int | None,
        max_price: int | None,
        sort_by: str,
        sort_order: str,
        page: int,
        page_size: int,
    ) -> AuctionPage:
        if min_price is not None and max_price is not None and min_price > max_price:
            raise AuctionDataError("min_price must not be greater than max_price")
        now = utc_now()
        query = public_query(now, availability, search, category, min_price, max_price)
        total = await self.repository.count_public(query)
        auctions = await self.repository.find_public(
            query, sort_by, 1 if sort_order == "asc" else -1,
            (page - 1) * page_size, page_size
        )
        return AuctionPage(
            items=[auction_response(item, now) for item in auctions],
            page=page, page_size=page_size, total=total,
            pages=(total + page_size - 1) // page_size,
        )

    async def list_by_seller(self, owner: User, page: int, page_size: int) -> AuctionPage:
        now = utc_now()
        total = await self.repository.count_by_seller(owner.id)
        auctions = await self.repository.find_by_seller(
            owner.id, (page - 1) * page_size, page_size
        )
        return AuctionPage(
            items=[auction_response(item, now) for item in auctions],
            page=page, page_size=page_size, total=total,
            pages=(total + page_size - 1) // page_size,
        )
