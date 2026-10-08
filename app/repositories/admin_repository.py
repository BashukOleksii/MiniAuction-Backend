from datetime import datetime
from typing import Any
from uuid import uuid4

from pymongo import ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase

from app.models.auction import Auction
from app.models.common import utc_now
from app.models.user import User


class AdminRepository:
    def __init__(self, db: AsyncDatabase):
        self.users = db["users"]
        self.auctions = db["auctions"]
        self.bids = db["bids"]
        self.audit = db["admin_audit_logs"]

    async def get_user(self, user_id: str) -> User | None:
        document = await self.users.find_one({"_id": user_id})
        return User.model_validate(document) if document is not None else None

    async def list_users(
        self, query: dict[str, Any], skip: int, limit: int
    ) -> list[User]:
        cursor = (
            self.users.find(query)
            .sort([("created_at", -1), ("_id", 1)])
            .skip(skip)
            .limit(limit)
        )
        return [User.model_validate(doc) for doc in await cursor.to_list(length=limit)]

    async def count_users(self, query: dict[str, Any]) -> int:
        return await self.users.count_documents(query)

    async def update_user_active(
        self, user_id: str, expected_active: bool, new_active: bool
    ) -> User | None:
        document = await self.users.find_one_and_update(
            {"_id": user_id, "role": "user", "is_active": expected_active},
            {
                "$set": {"is_active": new_active, "updated_at": utc_now()},
                "$inc": {"token_version": 1},
            },
            return_document=ReturnDocument.AFTER,
        )
        return User.model_validate(document) if document is not None else None

    async def get_auction(self, auction_id: str) -> Auction | None:
        document = await self.auctions.find_one({"_id": auction_id})
        return Auction.model_validate(document) if document is not None else None

    async def list_auctions(
        self, query: dict[str, Any], skip: int, limit: int
    ) -> list[Auction]:
        cursor = (
            self.auctions.find(query)
            .sort([("created_at", -1), ("_id", 1)])
            .skip(skip)
            .limit(limit)
        )
        return [Auction.model_validate(doc) for doc in await cursor.to_list(length=limit)]

    async def count_auctions(self, query: dict[str, Any]) -> int:
        return await self.auctions.count_documents(query)

    async def has_bids(self, auction_id: str) -> bool:
        return await self.bids.find_one({"auction_id": auction_id}, {"_id": 1}) is not None

    async def cancel_no_bid_auction(
        self,
        auction_id: str,
        expected_status: str,
        starting_price: int,
        now: datetime,
    ) -> Auction | None:
        # Bid module also requires active status in its atomic update.
        # The bid_count condition covers records created by the bidding branch;
        # a legacy document may legitimately have no bid_count field.
        query: dict[str, Any] = {
            "_id": auction_id,
            "status": expected_status,
            "leader_id": None,
            "starting_price": starting_price,
            "current_price": starting_price,
            "bid_count": {"$in": [0, None]},
        }
        if expected_status == "active":
            query["ends_at"] = {"$gt": now}
        document = await self.auctions.find_one_and_update(
            query,
            {"$set": {"status": "cancelled", "updated_at": now}},
            return_document=ReturnDocument.AFTER,
        )
        return Auction.model_validate(document) if document is not None else None

    async def count_bids(self) -> int:
        return await self.bids.count_documents({})

    async def add_audit(
        self, *, actor_id: str, action: str, target_id: str, reason: str
    ) -> None:
        await self.audit.insert_one(
            {
                "_id": str(uuid4()),
                "actor_id": actor_id,
                "action": action,
                "target_id": target_id,
                "reason": reason,
                "created_at": utc_now(),
            }
        )

    async def list_audit(
        self, query: dict[str, Any], skip: int, limit: int
    ) -> list[dict[str, Any]]:
        cursor = (
            self.audit.find(query)
            .sort([("created_at", -1), ("_id", 1)])
            .skip(skip)
            .limit(limit)
        )
        return await cursor.to_list(length=limit)

    async def count_audit(self, query: dict[str, Any]) -> int:
        return await self.audit.count_documents(query)
