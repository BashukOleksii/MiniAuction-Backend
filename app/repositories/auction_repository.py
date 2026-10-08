from datetime import datetime
from typing import Any

from pymongo import ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase

from app.models.auction import Auction, AuctionStatus
from app.models.common import utc_now


class AuctionRepository:
    def __init__(self, db: AsyncDatabase):
        self.collection = db["auctions"]

    async def create(self, auction: Auction) -> Auction:
        await self.collection.insert_one(auction.model_dump(by_alias=True, mode="python"))
        return auction

    async def get_by_id(self, auction_id: str) -> Auction | None:
        document = await self.collection.find_one({"_id": auction_id})
        return Auction.model_validate(document) if document is not None else None

    async def update_draft(
        self, auction_id: str, seller_id: str, changes: dict[str, Any]
    ) -> Auction | None:
        document = await self.collection.find_one_and_update(
            {"_id": auction_id, "seller_id": seller_id, "status": AuctionStatus.DRAFT.value},
            {"$set": {**changes, "updated_at": utc_now()}},
            return_document=ReturnDocument.AFTER,
        )
        return Auction.model_validate(document) if document is not None else None

    async def publish(
        self, auction_id: str, seller_id: str, now: datetime
    ) -> Auction | None:
        document = await self.collection.find_one_and_update(
            {
                "_id": auction_id,
                "seller_id": seller_id,
                "status": AuctionStatus.DRAFT.value,
                "ends_at": {"$gt": now},
            },
            {"$set": {"status": AuctionStatus.ACTIVE.value, "updated_at": utc_now()}},
            return_document=ReturnDocument.AFTER,
        )
        return Auction.model_validate(document) if document is not None else None

    async def cancel(
        self,
        auction_id: str,
        seller_id: str,
        expected_status: str,
        expected_price: int,
        now: datetime,
    ) -> Auction | None:
        # Блокуємо скасування одночасно з прийняттям ставки.
        # Старі документи можуть не мати bid_count.
        query: dict[str, Any] = {
            "_id": auction_id,
            "seller_id": seller_id,
            "status": expected_status,
            "current_price": expected_price,
            "leader_id": None,
            "bid_count": {"$in": [0, None]},
        }
        if expected_status == AuctionStatus.ACTIVE.value:
            query["ends_at"] = {"$gt": now}
        document = await self.collection.find_one_and_update(
            query,
            {"$set": {"status": AuctionStatus.CANCELLED.value, "updated_at": utc_now()}},
            return_document=ReturnDocument.AFTER,
        )
        return Auction.model_validate(document) if document is not None else None

    async def find_public(
        self,
        mongo_filter: dict[str, Any],
        sort_field: str,
        sort_direction: int,
        skip: int,
        limit: int,
    ) -> list[Auction]:
        cursor = (
            self.collection.find(mongo_filter)
            .sort([(sort_field, sort_direction), ("_id", 1)])
            .skip(skip)
            .limit(limit)
        )
        return [Auction.model_validate(doc) for doc in await cursor.to_list(length=limit)]

    async def count_public(self, mongo_filter: dict[str, Any]) -> int:
        return await self.collection.count_documents(mongo_filter)

    async def find_by_seller(
        self, seller_id: str, skip: int, limit: int
    ) -> list[Auction]:
        cursor = (
            self.collection.find({"seller_id": seller_id})
            .sort([("created_at", -1), ("_id", 1)])
            .skip(skip)
            .limit(limit)
        )
        return [Auction.model_validate(doc) for doc in await cursor.to_list(length=limit)]

    async def count_by_seller(self, seller_id: str) -> int:
        return await self.collection.count_documents({"seller_id": seller_id})
