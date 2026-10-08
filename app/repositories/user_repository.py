from typing import Any

from pymongo import ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase

from app.models.common import utc_now
from app.models.user import User


class UserRepository:

    def __init__(self, db: AsyncDatabase):
        self.collection = db["users"]

    async def get_by_id(self, user_id: str) -> User | None:
        document = await self.collection.find_one({"_id": user_id})
        return User.model_validate(document) if document is not None else None

    async def get_by_email(self, email: str) -> User | None:
        document = await self.collection.find_one({"email": email.lower()})
        return User.model_validate(document) if document is not None else None

    async def get_by_username(self, username: str) -> User | None:
        document = await self.collection.find_one({"username": username})
        return User.model_validate(document) if document is not None else None

    async def create(self, user: User) -> User:
        document = user.model_dump(by_alias=True, mode="python")
        await self.collection.insert_one(document)
        return user

    async def update_profile(self, user_id: str, changes: dict[str, Any]) -> User | None:
        document = await self.collection.find_one_and_update(
            {"_id": user_id, "is_active": True},
            {"$set": {**changes, "updated_at": utc_now()}},
            return_document=ReturnDocument.AFTER,
        )
        return User.model_validate(document) if document is not None else None

    async def update_password(
        self,
        user_id: str,
        expected_hash: str,
        new_password_hash: str,
    ) -> User | None:
        document = await self.collection.find_one_and_update(
            {
                "_id": user_id,
                "password_hash": expected_hash,
                "is_active": True,
            },
            {
                "$set": {
                    "password_hash": new_password_hash,
                    "updated_at": utc_now(),
                },
                "$inc": {"token_version": 1},
            },
            return_document=ReturnDocument.AFTER,
        )
        return User.model_validate(document) if document is not None else None
