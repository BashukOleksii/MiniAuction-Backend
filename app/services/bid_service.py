import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from pymongo import AsyncMongoClient
from pymongo.errors import DuplicateKeyError, PyMongoError

from app.models.auction import Auction
from app.models.bid import Bid
from app.models.user import User
from app.repositories.auction_repository import AuctionRepository
from app.repositories.bid_repository import BidRepository
from app.schemas.bid import BidResponse, CreateBidRequest


class BidService:
    """
    Сервіс бізнес-логіки торгів та конкурентності (Розробник 2).
    Реалізує вимоги B1–B10 та сценарії конкурентних ставок із ТЗ.
    """

    def __init__(
        self,
        mongo_client: AsyncMongoClient,
        bid_repo: BidRepository,
        auction_repo: AuctionRepository,
        max_retries: int = 5,
    ) -> None:
        self.mongo_client = mongo_client
        self.bid_repo = bid_repo
        self.auction_repo = auction_repo
        self.max_retries = max_retries

    # =========================================================================
    # B2. validate_bid_amount
    # =========================================================================
    @staticmethod
    def validate_bid_amount(amount: int) -> None:
        """Перевіряє, що сума є суворо цілим додатним числом (gt=0)."""
        if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "INVALID_BID_AMOUNT",
                    "message": "Bid amount must be a strictly positive integer",
                },
            )

    # =========================================================================
    # B3. calculate_minimum_bid
    # =========================================================================
    @staticmethod
    def calculate_minimum_bid(auction: Auction) -> int:
        """Обчислює current_price + min_bid_step (чиста функція)."""
        return auction.current_price + auction.min_bid_step

    # =========================================================================
    # B4. validate_bidder
    # =========================================================================
    @staticmethod
    def validate_bidder(auction: Auction, user: User) -> None:
        """Перевіряє право користувача робити ставку. Власник відхиляється 403 OWN_AUCTION."""
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "USER_INACTIVE",
                    "message": "User account is inactive",
                },
            )
        if auction.seller_id == user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "OWN_AUCTION",
                    "message": "Seller cannot bid on their own auction",
                },
            )

    # =========================================================================
    # B5. validate_auction_bidding_window
    # =========================================================================
    @staticmethod
    def validate_auction_bidding_window(auction: Auction, now: datetime) -> None:
        """Перевіряє вікно торгів (starts_at <= now < ends_at) та статус active."""
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

    # =========================================================================
    # B6. validate_bid_step
    # =========================================================================
    def validate_bid_step(self, auction: Auction, amount: int) -> None:
        """Перевіряє, чи покриває сума обов'язковий мінімальний крок."""
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

    # =========================================================================
    # B10. build_bid_response
    # =========================================================================
    @staticmethod
    def build_bid_response(bid: Bid) -> BidResponse:
        """Формує безпечний BidResponse DTO."""
        return BidResponse(
            id=str(bid.id),
            auction_id=bid.auction_id,
            bidder_id=bid.bidder_id,
            amount=bid.amount,
            sequence=bid.sequence,
            created_at=bid.created_at,
        )

    # =========================================================================
    # B1, B7, B8, B9. place_bid
    # =========================================================================
    async def place_bid(
        self,
        auction_id: str,
        bid_in: CreateBidRequest,
        current_user: User,
    ) -> BidResponse:
        """
        Головна атомарна операція торгів:
        - B2: Валідація суми
        - A3: Перевірка idempotency за request_id
        - B8: Цикл повторних спроб (bounded retry) при конкурентному навантаженні
        - B7: Виконання MongoDB-транзакції з conditional update лота
        - B9: Встановлення послідовності sequence
        """
        req_id_str = str(bid_in.request_id)
        self.validate_bid_amount(bid_in.amount)

        # 1. Перевірка ідемпотентності до відкриття сесій/транзакцій
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
            return self.build_bid_response(existing_bid)

        # 2. Транзакційне виконання торгів з обмеженим retry
        for _ in range(self.max_retries):
            # Читання свіжого стану аукціону
            raw_auction = await self.auction_repo.get_by_id(auction_id)
            if not raw_auction:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "code": "AUCTION_NOT_FOUND",
                        "message": "Auction not found",
                    },
                )

            now = datetime.now(timezone.utc)

            # Перевірки бізнес-інваріантів перед транзакцією
            self.validate_bidder(raw_auction, current_user)
            self.validate_auction_bidding_window(raw_auction, now)
            self.validate_bid_step(raw_auction, bid_in.amount)

            async with self.mongo_client.start_session() as session:
                await session.start_transaction()
                try:
                    # B7 / A8: Умовне оновлення ціни, лідера та лічильника
                    updated_auction_doc = await self.bid_repo.update_auction_bid_state(
                        auction_id=raw_auction.id,
                        expected_price=raw_auction.current_price,
                        bidder_id=current_user.id,
                        new_amount=bid_in.amount,
                        now=now,
                        session=session,
                    )

                    if not updated_auction_doc:
                        # Конкурентний запит змінив стан — відкочуємо та робимо retry
                        await session.abort_transaction()
                        continue

                    # B9: Sequence призначається з нового атомарного bid_count
                    new_sequence = updated_auction_doc["bid_count"]

                    new_bid = Bid(
                        id=str(uuid.uuid4()),
                        auction_id=raw_auction.id,
                        bidder_id=current_user.id,
                        amount=bid_in.amount,
                        sequence=new_sequence,
                        request_id=req_id_str,
                        created_at=now,
                    )

                    # B1 / A1: Створення ставки у тій самій сесії
                    created_bid = await self.bid_repo.create_bid(new_bid, session=session)
                    await session.commit_transaction()

                    return self.build_bid_response(created_bid)

                except DuplicateKeyError:
                    await session.abort_transaction()
                    # Перевірка на паралельний дублікат за request_id
                    existing = await self.bid_repo.get_bid_by_request_id(
                        auction_id, current_user.id, req_id_str
                    )
                    if existing and existing.amount == bid_in.amount:
                        return self.build_bid_response(existing)
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={
                            "code": "CONCURRENT_DUPLICATE_KEY",
                            "message": "Duplicate key conflict during concurrent write",
                        },
                    )
                except PyMongoError:
                    # Transient помилка драйвера під час конкурентного запису
                    await session.abort_transaction()
                    continue
                except Exception:
                    await session.abort_transaction()
                    raise

        # 3. Якщо всі retry вичерпані — повторно перевіряємо актуальний лот для точного коду
        fresh_auction = await self.auction_repo.get_by_id(auction_id)
        if fresh_auction and bid_in.amount < self.calculate_minimum_bid(fresh_auction):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "BID_TOO_LOW",
                    "message": "Bid amount is too low due to recent concurrent bids",
                    "current_price": fresh_auction.current_price,
                    "minimum_bid": self.calculate_minimum_bid(fresh_auction),
                },
            )

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "CONTROLLED_CONCURRENCY_ERROR",
                "message": "Could not finalize bid due to high concurrent load. Please retry.",
            },
        )