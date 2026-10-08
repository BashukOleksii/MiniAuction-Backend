from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status

from app.models.auction import Auction
from app.repositories.auction_finalization_repository import AuctionFinalizationRepository
from app.repositories.auction_repository import AuctionRepository
from app.schemas.auction_result import AuctionResultResponse


class AuctionFinalizationService:
    def __init__(
        self,
        auction_repo: AuctionRepository,
        finalization_repo: AuctionFinalizationRepository,
    ) -> None:
        self.auction_repo = auction_repo
        self.finalization_repo = finalization_repo

    # =========================================================================
    # E1. is_auction_expired
    # =========================================================================
    @staticmethod
    def is_auction_expired(auction: Auction, now: datetime) -> bool:
        """now >= ends_at означає точне завершення."""
        return now >= auction.ends_at

    # =========================================================================
    # E3. determine_winner
    # =========================================================================
    @staticmethod
    def determine_winner(auction: Auction) -> tuple[Optional[str], Optional[int]]:
        """
        Визначає (winner_id, winning_bid).
        Якщо bid_count == 0 -> (None, None).
        Інакше -> (leader_id, current_price).
        """
        if auction.bid_count == 0 or not auction.leader_id:
            return None, None
        return auction.leader_id, auction.current_price

    # =========================================================================
    # E2. finalize_auction
    # =========================================================================
    async def finalize_auction(self, auction_id: str) -> Auction:
        """
        Матеріалізує кінцевий статус та переможця (E2).
        Ідемпотентний: повторні виклики повертають уже збережений результат.
        """
        auction = await self.auction_repo.get_by_id(auction_id)
        if not auction:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "AUCTION_NOT_FOUND", "message": "Auction not found"},
            )

        now = datetime.now(timezone.utc)

        # Якщо вже завершений або скасований — повертаємо поточний стан
        if auction.status == "finished":
            return auction

        if not self.is_auction_expired(auction, now):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "AUCTION_STILL_ACTIVE",
                    "message": "Cannot finalize auction before ends_at",
                },
            )

        winner_id, _ = self.determine_winner(auction)

        # Атомарно фіксуємо в БД
        updated_doc = await self.finalization_repo.finalize_auction_atomically(
            auction_id=auction.id,
            winner_id=winner_id,
            now=now,
        )

        if updated_doc:
            return Auction.model_validate(updated_doc)

        # Якщо інший процес встиг фіналізувати раніше — перечитуємо
        fresh_auction = await self.auction_repo.get_by_id(auction_id)
        return fresh_auction or auction

    # =========================================================================
    # E6. ensure_auction_finalized
    # =========================================================================
    async def ensure_auction_finalized(self, auction: Auction, now: datetime) -> Auction:
        """
        Лінива фіналізація: якщо час вийшов, а статус ще active — завершує лот.
        Не робить зайвих записів, якщо лот уже finished.
        """
        if auction.status == "active" and self.is_auction_expired(auction, now):
            return await self.finalize_auction(auction.id)
        return auction

    # =========================================================================
    # E4. get_auction_result
    # =========================================================================
    async def get_auction_result(self, auction_id: str) -> AuctionResultResponse:
        """
        Повертає підсумок результатів лота (E4).
        """
        auction = await self.auction_repo.get_by_id(auction_id)
        if not auction:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "AUCTION_NOT_FOUND", "message": "Auction not found"},
            )

        now = datetime.now(timezone.utc)

        # Якщо ще триває
        if auction.status == "active" and not self.is_auction_expired(auction, now):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "AUCTION_NOT_FINISHED",
                    "message": "Auction is still active",
                },
            )

        # Дофіналізовуємо за потреби
        finalized_auction = await self.ensure_auction_finalized(auction, now)
        winner_id, winning_bid = self.determine_winner(finalized_auction)

        return AuctionResultResponse(
            auction_id=finalized_auction.id,
            status=finalized_auction.status,
            winner_id=finalized_auction.winner_id or winner_id,
            winning_bid=winning_bid,
            total_bids=finalized_auction.bid_count,
            ended_at=finalized_auction.ends_at,
        )