from pymongo.asynchronous.database import AsyncDatabase

from app.models.user import User


class UserRepository:
    def __init__(self, db: AsyncDatabase):
        self.collection = db["users"]

    async def get_by_id(self, user_id: str) -> User | None:
        document = await self.collection.find_one(
            {"_id": user_id}
        )

        if document is None:
            return None

        return User.model_validate(document)

    async def get_by_email(self, email: str) -> User | None:
        document = await self.collection.find_one(
            {"email": email.lower()}
        )

        if document is None:
            return None

        return User.model_validate(document)

    async def get_by_username(
        self,
        username: str
    ) -> User | None:
        document = await self.collection.find_one(
            {"username": username}
        )

        if document is None:
            return None

        return User.model_validate(document)

    async def create(self, user: User) -> User:
        document = user.model_dump(
            by_alias=True,
            mode="python"
        )

        await self.collection.insert_one(document)

        return user
