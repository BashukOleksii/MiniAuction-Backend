import logging
import re
from datetime import datetime
from typing import Any, Literal

from app.models.auction import Auction
from app.models.common import utc_now
from app.models.user import User
from app.repositories.admin_repository import AdminRepository
from app.schemas.admin import (
    AdminAuctionPage,
    AdminAuditLogResponse,
    AdminAuditPage,
    AdminStatistics,
    AdminUserPage,
    AdminUserResponse,
)
from app.services.auction_service import auction_response

logger = logging.getLogger(__name__)


class AdminNotFoundError(Exception):
    pass


class AdminConflictError(Exception):
    pass


def user_query(
    search: str | None, role: Literal["user", "admin"] | None, active: bool | None
) -> dict[str, Any]:
    query: dict[str, Any] = {}
    if role is not None:
        query["role"] = role
    if active is not None:
        query["is_active"] = active
    if search and search.strip():
        safe = re.escape(search.strip())
        query["$or"] = [
            {"username": {"$regex": safe, "$options": "i"}},
            {"email": {"$regex": safe, "$options": "i"}},
        ]
    return query


def auction_query(
    now: datetime,
    state: Literal["draft", "scheduled", "active", "finished", "cancelled"] | None,
    search: str | None,
    seller_id: str | None,
    category: str | None,
) -> dict[str, Any]:
    query: dict[str, Any] = {}
    if state == "scheduled":
        query.update({"status": "active", "starts_at": {"$gt": now}})
    elif state == "active":
        query.update({"status": "active", "starts_at": {"$lte": now}, "ends_at": {"$gt": now}})
    elif state == "finished":
        query["$or"] = [
            {"status": "finished"},
            {"status": "active", "ends_at": {"$lte": now}},
        ]
    elif state is not None:
        query["status"] = state
    if seller_id is not None:
        query["seller_id"] = seller_id
    if category is not None:
        query["category"] = category.strip().lower()
    if search and search.strip():
        pattern = re.escape(search.strip())
        # $and prevents collisions with the $or used for finished auctions.
        query["$and"] = [
            {"$or": [
                {"title": {"$regex": pattern, "$options": "i"}},
                {"description": {"$regex": pattern, "$options": "i"}},
            ]}
        ]
    return query


class AdminService:
    def __init__(self, repository: AdminRepository):
        self.repository = repository

    async def _record(self, *, admin_id: str, action: str, target_id: str, reason: str) -> None:
        # Best-effort MVP audit: operational result must not be misreported if
        # the audit collection is temporarily unavailable after a committed change.
        # For strict compliance, move the mutation + audit into one DB transaction.
        try:
            await self.repository.add_audit(
                actor_id=admin_id, action=action, target_id=target_id, reason=reason
            )
        except Exception:
            logger.exception("Admin audit write failed for action %s target %s", action, target_id)

    async def list_users(
        self, *, search: str | None, role: str | None,
        active: bool | None, page: int, page_size: int
    ) -> AdminUserPage:
        query = user_query(search, role, active)
        total = await self.repository.count_users(query)
        users = await self.repository.list_users(query, (page - 1) * page_size, page_size)
        return AdminUserPage(
            items=[AdminUserResponse.model_validate(user) for user in users],
            total=total, page=page, page_size=page_size,
            pages=(total + page_size - 1) // page_size,
        )

    async def get_user(self, user_id: str) -> AdminUserResponse:
        user = await self.repository.get_user(user_id)
        if user is None:
            raise AdminNotFoundError("User not found")
        return AdminUserResponse.model_validate(user)

    async def set_user_active(
        self, *, admin: User, user_id: str, is_active: bool, reason: str
    ) -> AdminUserResponse:
        if admin.id == user_id:
            raise AdminConflictError("An administrator cannot change their own status")
        target = await self.repository.get_user(user_id)
        if target is None:
            raise AdminNotFoundError("User not found")
        if target.role == "admin":
            raise AdminConflictError("Administrator accounts cannot be blocked here")
        if target.is_active == is_active:
            raise AdminConflictError("User is already in the requested state")
        updated = await self.repository.update_user_active(
            user_id, expected_active=target.is_active, new_active=is_active
        )
        if updated is None:
            raise AdminConflictError("User changed concurrently; reload and retry")
        await self._record(
            admin_id=admin.id,
            action="user.unblock" if is_active else "user.block",
            target_id=user_id,
            reason=reason,
        )
        return AdminUserResponse.model_validate(updated)

    async def list_auctions(
        self, *, state: str | None, search: str | None,
        seller_id: str | None, category: str | None, page: int, page_size: int
    ) -> AdminAuctionPage:
        now = utc_now()
        query = auction_query(now, state, search, seller_id, category)
        total = await self.repository.count_auctions(query)
        auctions = await self.repository.list_auctions(
            query, (page - 1) * page_size, page_size
        )
        return AdminAuctionPage(
            items=[auction_response(a, now) for a in auctions],
            total=total, page=page, page_size=page_size,
            pages=(total + page_size - 1) // page_size,
        )

    async def get_auction(self, auction_id: str) -> Auction:
        auction = await self.repository.get_auction(auction_id)
        if auction is None:
            raise AdminNotFoundError("Auction not found")
        return auction

    async def cancel_auction(self, *, admin: User, auction_id: str, reason: str) -> Auction:
        auction = await self.get_auction(auction_id)
        if auction.status not in ("draft", "active"):
            raise AdminConflictError("Auction cannot be cancelled in this state")
        now = utc_now()
        if auction.status == "active" and auction.ends_at <= now:
            raise AdminConflictError("Finished auctions cannot be cancelled")
        if auction.leader_id is not None or auction.current_price != auction.starting_price:
            raise AdminConflictError("Auctions with bids cannot be cancelled")
        # Check the separate bids collection as well, not only the cached auction state.
        if await self.repository.has_bids(auction_id):
            raise AdminConflictError("Auction has bid history and cannot be cancelled")
        updated = await self.repository.cancel_no_bid_auction(
            auction_id, str(auction.status), auction.starting_price, now
        )
        if updated is None:
            raise AdminConflictError("Auction changed concurrently; reload and retry")
        await self._record(
            admin_id=admin.id, action="auction.cancel",
            target_id=auction_id, reason=reason,
        )
        return updated

    async def statistics(self) -> AdminStatistics:
        now = utc_now()
        users_total = await self.repository.count_users({})
        users_active = await self.repository.count_users({"is_active": True})
        return AdminStatistics(
            users_total=users_total,
            users_active=users_active,
            users_blocked=users_total - users_active,
            auctions_total=await self.repository.count_auctions({}),
            auctions_draft=await self.repository.count_auctions({"status": "draft"}),
            auctions_scheduled=await self.repository.count_auctions(
                auction_query(now, "scheduled", None, None, None)
            ),
            auctions_active=await self.repository.count_auctions(
                auction_query(now, "active", None, None, None)
            ),
            auctions_finished=await self.repository.count_auctions(
                auction_query(now, "finished", None, None, None)
            ),
            auctions_cancelled=await self.repository.count_auctions({"status": "cancelled"}),
            bids_total=await self.repository.count_bids(),
        )

    async def audit_logs(
        self, *, action: str | None, page: int, page_size: int
    ) -> AdminAuditPage:
        query = {"action": action} if action is not None else {}
        total = await self.repository.count_audit(query)
        docs = await self.repository.list_audit(query, (page - 1) * page_size, page_size)
        return AdminAuditPage(
            items=[AdminAuditLogResponse.model_validate({
                **doc, "id": doc["_id"]
            }) for doc in docs],
            total=total, page=page, page_size=page_size,
            pages=(total + page_size - 1) // page_size,
        )
