from datetime import datetime, timezone

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

    @staticmethod
    def is_auction_expired(auction: Auction, now: datetime) -> bool:
        return now >= auction.ends_at

    @staticmethod
    def determine_winner(auction: Auction) -> tuple[str | None, int | None]:
        if auction.bid_count == 0 or not auction.leader_id:
            return None, None
        return auction.leader_id, auction.current_price

    async def finalize_auction(self, auction_id: str) -> Auction:
        auction = await self.auction_repo.get_by_id(auction_id)
        if auction is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "AUCTION_NOT_FOUND", "message": "Auction not found"},
            )
        if auction.status == "finished":
            return auction
        # Не можна фіналізувати draft/cancelled навіть після ends_at.
        if auction.status != "active":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "AUCTION_NOT_ACTIVE", "message": "Auction is not active"},
            )
        now = datetime.now(timezone.utc)
        if not self.is_auction_expired(auction, now):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "AUCTION_STILL_ACTIVE", "message": "Auction has not expired"},
            )
        winner_id, _ = self.determine_winner(auction)
        updated_doc = await self.finalization_repo.finalize_auction_atomically(
            auction_id=auction.id,
            winner_id=winner_id,
            now=now,
        )
        if updated_doc is not None:
            return Auction.model_validate(updated_doc)
        fresh = await self.auction_repo.get_by_id(auction_id)
        if fresh is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "AUCTION_NOT_FOUND", "message": "Auction not found"},
            )
        return fresh

    async def ensure_auction_finalized(self, auction: Auction, now: datetime) -> Auction:
        if auction.status == "active" and self.is_auction_expired(auction, now):
            return await self.finalize_auction(auction.id)
        return auction

    async def get_auction_result(self, auction_id: str) -> AuctionResultResponse:
        auction = await self.auction_repo.get_by_id(auction_id)
        if auction is None or auction.status == "draft":
            # Публічний endpoint не розкриває приватні чернетки.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "AUCTION_NOT_FOUND", "message": "Auction not found"},
            )
        if auction.status == "cancelled":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "AUCTION_CANCELLED", "message": "Auction was cancelled"},
            )
        now = datetime.now(timezone.utc)
        if auction.status == "active" and not self.is_auction_expired(auction, now):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "AUCTION_NOT_FINISHED", "message": "Auction has not finished"},
            )
        finalized = await self.ensure_auction_finalized(auction, now)
        if finalized.status != "finished":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "AUCTION_NOT_FINISHED", "message": "Auction is not finished"},
            )
        winner_id, winning_bid = self.determine_winner(finalized)
        return AuctionResultResponse(
            auction_id=finalized.id,
            status="finished",
            winner_id=finalized.winner_id or winner_id,
            winning_bid=winning_bid,
            total_bids=finalized.bid_count,
            ended_at=finalized.ends_at,
        )
