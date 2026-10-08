from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status

from app.models.auction import Auction
from app.models.bid import Bid
from app.models.user import User
from app.repositories.auction_repository import AuctionRepository
from app.repositories.bid_repository import BidRepository
from app.schemas.auction_state import AuctionStateResponse
from app.services.auction_finalization_service import AuctionFinalizationService


class AuctionStateService:
    def __init__(
        self,
        auction_repo: AuctionRepository,
        bid_repo: BidRepository,
        finalization_service: AuctionFinalizationService,
    ) -> None:
        self.auction_repo = auction_repo
        self.bid_repo = bid_repo
        self.finalization_service = finalization_service

    # =========================================================================
    # D1. get_effective_status
    # =========================================================================
    @staticmethod
    def get_effective_status(auction: Auction, now: datetime) -> str:
        """
        Єдина чиста функція обчислення ефективного статусу для всього бекенду (D1):
        - draft та cancelled мають абсолютний пріоритет над часом.
        - finished залишається finished незалежно від дат.
        - Якщо status == 'active':
            now < starts_at          -> scheduled
            starts_at <= now < ends_at -> active
            now >= ends_at           -> finished
        """
        if auction.status in ("draft", "cancelled", "finished"):
            return auction.status

        if auction.status == "active":
            if now < auction.starts_at:
                return "scheduled"
            if now >= auction.ends_at:
                return "finished"
            return "active"

        return auction.status

    # =========================================================================
    # D4. get_remaining_time
    # =========================================================================
    @staticmethod
    def get_remaining_time(auction: Auction, now: datetime) -> int:
        """Розраховує max(0, ends_at - now) у цілих секундах."""
        diff = int((auction.ends_at - now).total_seconds())
        return max(0, diff)

    # =========================================================================
    # D5. is_user_winning
    # =========================================================================
    @classmethod
    def is_user_winning(cls, auction: Auction, user: Optional[User], effective_status: str) -> bool:
        """Повертає True тільки якщо user є, він лідер і лот активний."""
        if not user or not auction.leader_id:
            return False
        return effective_status == "active" and auction.leader_id == user.id

    # =========================================================================
    # D6. get_minimum_next_bid
    # =========================================================================
    @staticmethod
    def get_minimum_next_bid(auction: Auction, effective_status: str) -> Optional[int]:
        """Повертає наступну ставку або None для завершеного/неактивного лота."""
        if effective_status in ("finished", "cancelled", "draft"):
            return None
        return auction.current_price + auction.min_bid_step

    # =========================================================================
    # D2. get_auction_state
    # =========================================================================
    async def get_auction_state(
        self,
        auction_id: str,
        optional_user: Optional[User] = None,
    ) -> AuctionStateResponse:
        """
        Легкий запит за одне читання лота для швидкого polling (D2).
        """
        auction = await self.auction_repo.get_by_id(auction_id)
        if not auction:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "AUCTION_NOT_FOUND", "message": "Auction not found"},
            )

        now = datetime.now(timezone.utc)

        # Захист чужих draft
        if auction.status == "draft":
            if not optional_user or optional_user.id != auction.seller_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"code": "AUCTION_NOT_FOUND", "message": "Auction not found"},
                )

        # Дофіналізація при завершенні часу (E6)
        auction = await self.finalization_service.ensure_auction_finalized(auction, now)

        effective_status = self.get_effective_status(auction, now)
        remaining_seconds = self.get_remaining_time(auction, now)
        min_next_bid = self.get_minimum_next_bid(auction, effective_status)
        is_winning = self.is_user_winning(auction, optional_user, effective_status)

        return AuctionStateResponse(
            auction_id=auction.id,
            status=effective_status,
            current_price=auction.current_price,
            minimum_bid=min_next_bid,
            bid_count=auction.bid_count,
            leader_id=auction.leader_id,
            ends_at=auction.ends_at,
            server_time=now,
            remaining_seconds=remaining_seconds,
            is_winning=is_winning,
        )

    # =========================================================================
    # F1. get_recent_bids
    # =========================================================================
    async def get_recent_bids(
        self,
        auction_id: str,
        limit: int = 10,
        after_sequence: Optional[int] = None,
    ) -> list[Bid]:
        """
        Отримання свіжих ставок без повного сканування бази (F1).
        """
        # Обмежуємо ліміт від 1 до 20
        safe_limit = max(1, min(limit, 20))
        return await self.bid_repo.get_recent_bids(
            auction_id=auction_id,
            limit=safe_limit,
            after_sequence=after_sequence,
        )