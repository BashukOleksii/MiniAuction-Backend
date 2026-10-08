import uuid
from datetime import datetime, timezone
from typing import Any

from pymongo import ReturnDocument
from pymongo.asynchronous.client_session import AsyncClientSession

from app.models.bid import Bid


class BidRepository:
    """
    Репозиторій для роботи зі ставками та атомарними оновленнями торгів (Розробник 2).
    """

    def __init__(self, db: Any) -> None:
        self.bids_collection = db["bids"]
        self.auctions_collection = db["auctions"]

    # =========================================================================
    # A1. create_bid(bid, session)
    # =========================================================================
    async def create_bid(
        self,
        bid: Bid,
        session: AsyncClientSession,
    ) -> Bid:
        doc = bid.model_dump(by_alias=True)
        if not doc.get("_id"):
            doc["_id"] = str(uuid.uuid4())
        if not doc.get("created_at"):
            doc["created_at"] = datetime.now(timezone.utc)

        await self.bids_collection.insert_one(doc, session=session)
        return Bid.model_validate(doc)


    # =========================================================================
    # A2. get_bid_by_id(bid_id)
    # =========================================================================
    async def get_bid_by_id(
        self,
        bid_id: str,
        session: AsyncClientSession | None = None,
    ) -> Bid | None:
        """
        Знаходить конкретну ставку за її UUID (_id).
        """
        doc = await self.bids_collection.find_one({"_id": bid_id}, session=session)
        if not doc:
            return None
        return Bid.model_validate(doc)

    # =========================================================================
    # A3. get_bid_by_request_id(auction_id, bidder_id, request_id)
    # =========================================================================
    async def get_bid_by_request_id(
        self,
        auction_id: str,
        bidder_id: str,
        request_id: str,
        session: AsyncClientSession | None = None,
    ) -> Bid | None:
        """
        Шукає результат попереднього запиту за 3 полями для забезпечення ідемпотентності.
        """
        doc = await self.bids_collection.find_one(
            {
                "auction_id": auction_id,
                "bidder_id": bidder_id,
                "request_id": request_id,
            },
            session=session,
        )
        if not doc:
            return None
        return Bid.model_validate(doc)

    # =========================================================================
    # A4. get_auction_bids(auction_id, page, page_size)
    # =========================================================================
    async def get_auction_bids(
        self,
        auction_id: str,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Bid], int]:
        """
        Повертає історію прийнятих ставок лота з пагінацією.
        Сортування суворо за sequence DESC. Повертає (список_ставок, загальна_кількість).
        """
        skip = (page - 1) * page_size
        filter_query = {"auction_id": auction_id}

        total_bids = await self.bids_collection.count_documents(filter_query)

        cursor = (
            self.bids_collection.find(filter_query)
            .sort("sequence", -1)
            .skip(skip)
            .limit(page_size)
        )

        bids: list[Bid] = []
        async for doc in cursor:
            bids.append(Bid.model_validate(doc))

        return bids, total_bids

    # =========================================================================
    # A5. count_auction_bids(auction_id)
    # =========================================================================
    async def count_auction_bids(
        self,
        auction_id: str,
        session: AsyncClientSession | None = None,
    ) -> int:
        """
        Рахує кількість ставок за auction_id для звірки з bid_count або пагінації.
        """
        return await self.bids_collection.count_documents(
            {"auction_id": auction_id},
            session=session,
        )

    # =========================================================================
    # A6. get_user_bids(user_id, page, page_size)
    # =========================================================================
    async def get_user_bids(
        self,
        user_id: str,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Bid], int]:
        """
        Отримує власні ставки учасника.
        Сортування: created_at DESC зі стабільним tie-breaker sequence DESC.
        """
        skip = (page - 1) * page_size
        filter_query = {"bidder_id": user_id}

        total_bids = await self.bids_collection.count_documents(filter_query)

        cursor = (
            self.bids_collection.find(filter_query)
            .sort([("created_at", -1), ("sequence", -1)])
            .skip(skip)
            .limit(page_size)
        )

        bids: list[Bid] = []
        async for doc in cursor:
            bids.append(Bid.model_validate(doc))

        return bids, total_bids

    # =========================================================================
    # A7. get_latest_bid(auction_id)
    # =========================================================================
    async def get_latest_bid(
        self,
        auction_id: str,
        session: AsyncClientSession | None = None,
    ) -> Bid | None:
        """
        Діагностично отримує останню ставку лота з найбільшим sequence.
        """
        cursor = (
            self.bids_collection.find({"auction_id": auction_id}, session=session)
            .sort("sequence", -1)
            .limit(1)
        )
        async for doc in cursor:
            return Bid.model_validate(doc)
        return None

    # =========================================================================
    # F1. get_recent_bids(auction_id, limit, after_sequence)
    # =========================================================================
    async def get_recent_bids(
        self,
        auction_id: str,
        limit: int = 10,
        after_sequence: int | None = None,
    ) -> list[Bid]:
        """
        Повертає короткий список свіжих ставок для polling.
        Якщо передано after_sequence — фільтрує лише ставки з sequence > after_sequence.
        """
        query: dict[str, Any] = {"auction_id": auction_id}
        if after_sequence is not None:
            query["sequence"] = {"$gt": after_sequence}

        cursor = (
            self.bids_collection.find(query)
            .sort("sequence", -1)
            .limit(limit)
        )

        bids: list[Bid] = []
        async for doc in cursor:
            bids.append(Bid.model_validate(doc))
        return bids

    # =========================================================================
    # A8. update_auction_bid_state(...)
    # =========================================================================
    async def update_auction_bid_state(
        self,
        auction_id: str,
        expected_price: int,
        bidder_id: str,
        new_amount: int,
        now: datetime,
        session: AsyncClientSession,
    ) -> dict[str, Any] | None:
        """
        Умовно й атомарно оновлює Auction усередині активної транзакції:
        - Перевіряє оптимістичне блокування по current_price == expected_price
        - Перевіряє статус 'active'
        - Перевіряє серверний час: starts_at <= now < ends_at
        - Забороняє продавцю ставити на свій лот: seller_id != bidder_id
        - Інкрементує bid_count на 1 та оновлює ціну й лідера

        Повертає оновлений документ лота або None, якщо сталася зміна стану (конфлікт).
        """
        filter_query = {
            "_id": auction_id,
            "status": "active",
            "current_price": expected_price,
            "starts_at": {"$lte": now},
            "ends_at": {"$gt": now},
            "seller_id": {"$ne": bidder_id},
        }

        update_query = {
            "$set": {
                "current_price": new_amount,
                "leader_id": bidder_id,
                "updated_at": now,
            },
            "$inc": {
                "bid_count": 1,
            },
        }

        updated_auction = await self.auctions_collection.find_one_and_update(
            filter_query,
            update_query,
            session=session,
            return_document=ReturnDocument.AFTER,
        )

        return updated_auction