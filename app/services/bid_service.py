from datetime import datetime, timezone
from typing import Any, Optional
import uuid

from fastapi import HTTPException, status
from pymongo import AsyncMongoClient
from pymongo.errors import PyMongoError

from app.models.auction import Auction
from app.models.bid import Bid
from app.models.user import User
from app.repositories.auction_repository import AuctionRepository
from app.repositories.bid_repository import BidRepository
from app.schemas.bid import BidResponse, CreateBidRequest


class BidService:
    def __init__(
        self,
        mongo_client: AsyncMongoClient,
        bid_repo: BidRepository,
        auction_repo: AuctionRepository,
        max_retries: int = 3,
    ) -> None:
        self.mongo_client = mongo_client
        self.bid_repo = bid_repo
        self.auction_repo = auction_repo
        self.max_retries = max_retries

    # -------------------------------------------------------------------------
    # B2. validate_bid_amount
    # -------------------------------------------------------------------------
    @staticmethod
    def validate_bid_amount(amount: int) -> None:
        """Перевіряє, що сума є цілим числом більше 0."""
        if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "INVALID_BID_AMOUNT",
                    "message": "Bid amount must be a strictly positive integer",
                },
            )

    # -------------------------------------------------------------------------
    # B3. calculate_minimum_bid
    # -------------------------------------------------------------------------
    @staticmethod
    def calculate_minimum_bid(auction: Auction) -> int:
        """Чиста функція розрахунку мінімальної наступної ставки: current_price + min_bid_step."""
        return auction.current_price + auction.min_bid_step

    # -------------------------------------------------------------------------
    # B4. validate_bidder
    # -------------------------------------------------------------------------
    @staticmethod
    def validate_bidder(auction: Auction, user: User) -> None:
        """Перевіряє право користувача робити ставку. Власник не може ставити на свій лот."""
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "USER_INACTIVE", "message": "User account is inactive"},
            )
        if auction.seller_id == user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "OWN_AUCTION", "message": "Seller cannot bid on their own auction"},
            )

    # -------------------------------------------------------------------------
    # B5. validate_auction_bidding_window
    # -------------------------------------------------------------------------
    @staticmethod
    def validate_auction_bidding_window(auction: Auction, now: datetime) -> None:
        """Перевіряє вікно торгів та статус лота."""
        if auction.status != "active":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "AUCTION_NOT_ACTIVE",
                    "message": f"Auction is not active. Current status: {auction.status}",
                },
            )

        if now < auction.starts_at:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "AUCTION_NOT_STARTED",
                    "message": "Bidding has not started yet",
                },
            )

        if now >= auction.ends_at:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "AUCTION_CLOSED",
                    "message": "Auction bidding window has ended",
                },
            )

    # -------------------------------------------------------------------------
    # B6. validate_bid_step
    # -------------------------------------------------------------------------
    def validate_bid_step(self, auction: Auction, amount: int) -> None:
        """Перевіряє, чи сума ставки покриває мінімально дозволений крок."""
        minimum_bid = self.calculate_minimum_bid(auction)
        if amount < minimum_bid:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "BID_TOO_LOW",
                    "message": "Bid amount is too low",
                    "current_price": auction.current_price,
                    "minimum_bid": minimum_bid,
                },
            )

    # -------------------------------------------------------------------------
    # B10. build_bid_response
    # -------------------------------------------------------------------------
    @staticmethod
    def build_bid_response(bid: Bid) -> BidResponse:
        """Формує безпечний DTO об'єкт відповіді."""
        return BidResponse(
            id=str(bid.id),
            auction_id=bid.auction_id,
            bidder_id=bid.bidder_id,
            amount=bid.amount,
            sequence=bid.sequence,
            created_at=bid.created_at,
        )

    # -------------------------------------------------------------------------
    # B1, B7, B8, B9. place_bid (головна транзакційна операція)
    # -------------------------------------------------------------------------
    async def place_bid(
        self,
        auction_id: str,
        bid_in: CreateBidRequest,
        current_user: User,
    ) -> BidResponse:
        """
        Головна операція торгів:
        1. Перевірка валідності суми.
        2. Перевірка ідемпотентності (A3).
        3. Транзакційне conditional-оновлення лота та створення Bid з retry.
        """
        req_id_str = str(bid_in.request_id)
        self.validate_bid_amount(bid_in.amount)

        # 1. Перевірка ідемпотентності перед транзакцією
        existing_bid = await self.bid_repo.get_bid_by_request_id(
            auction_id=auction_id,
            bidder_id=current_user.id,
            request_id=req_id_str,
        )
        if existing_bid:
            if existing_bid.amount != bid_in.amount:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "IDEMPOTENCY_KEY_REUSED",
                        "message": "Request ID already used with a different amount",
                    },
                )
            # Успішний повторний виклик: повертаємо вже збережену ставку
            return self.build_bid_response(existing_bid)

        # 2. Цикл транзакції з обмеженим retry при гонці оновлень (B8)
        last_conflict_exception: Optional[HTTPException] = None

        for attempt in range(self.max_retries):
            # Завантажуємо актуальний стан аукціону
            auction = await self.auction_repo.get_by_id(auction_id)
            if not auction:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"code": "AUCTION_NOT_FOUND", "message": "Auction not found"},
                )

            now = datetime.now(timezone.utc)

            # Бізнес-перевірки до запису
            self.validate_bidder(auction, current_user)
            self.validate_auction_bidding_window(auction, now)
            self.validate_bid_step(auction, bid_in.amount)

            # Виконання атомарної транзакції (B7)
            try:
                async with self.mongo_client.start_session() as session:
                    await session.start_transaction()
                    try:
                        # Атомарне умовне оновлення лота (A8)
                        updated_auction_doc = await self.bid_repo.update_auction_bid_state(
                            auction_id=auction.id,
                            expected_price=auction.current_price,
                            bidder_id=current_user.id,
                            new_amount=bid_in.amount,
                            now=now,
                            session=session,
                        )

                        if not updated_auction_doc:
                            # Оптимістичне блокування не пройшло — інша ставка комітнулася раніше
                            await session.abort_transaction()
                            last_conflict_exception = HTTPException(
                                status_code=status.HTTP_409_CONFLICT,
                                detail={
                                    "code": "CONCURRENT_UPDATE_CONFLICT",
                                    "message": "Another bid was placed concurrently, retrying...",
                                },
                            )
                            continue

                        # B9: Новий sequence = оновлений bid_count із лота
                        new_sequence = updated_auction_doc["bid_count"]

                        # Створення об'єкта ставки
                        new_bid = Bid(
                            id=str(uuid.uuid4()),
                            auction_id=auction.id,
                            bidder_id=current_user.id,
                            amount=bid_in.amount,
                            sequence=new_sequence,
                            request_id=req_id_str,
                            created_at=now,
                        )

                        created_bid = await self.bid_repo.create_bid(new_bid, session=session)
                        await session.commit_transaction()

                        return self.build_bid_response(created_bid)

                    except Exception as tx_exc:
                        await session.abort_transaction()
                        raise tx_exc

            except HTTPException:
                raise
            except PyMongoError:
                # Мережеві чи транзакційні transient-помилки
                continue

        # Якщо всі спроби вичерпано через паралельні зміни
        if last_conflict_exception:
            # Фінальна перевірка для зрозумілого повідомлення клієнту
            fresh_auction = await self.auction_repo.get_by_id(auction_id)
            if fresh_auction and bid_in.amount < self.calculate_minimum_bid(fresh_auction):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "BID_TOO_LOW",
                        "message": "Bid amount is too low after concurrent updates",
                        "current_price": fresh_auction.current_price,
                        "minimum_bid": self.calculate_minimum_bid(fresh_auction),
                    },
                )
            raise last_conflict_exception

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "BID_CONCURRENCY_ERROR",
                "message": "Could not finalize bid due to high concurrent load. Please try again.",
            },
        )