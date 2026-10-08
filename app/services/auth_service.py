from pymongo.errors import DuplicateKeyError
from starlette.concurrency import run_in_threadpool

from app.core.security import hash_password
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.auth import RegisterRequest


class UserAlreadyExistsError(Exception):
    def __init__(self, field: str):
        self.field = field
        super().__init__(f"User conflict: {field}")


class AuthService:
    def __init__(self, repository: UserRepository):
        self.repository = repository

    async def register(self, data: RegisterRequest) -> User:
        existing_user = await self.repository.get_by_email(
            str(data.email)
        )

        if existing_user is not None:
            raise UserAlreadyExistsError("email")

        existing_user = await self.repository.get_by_username(
            data.username
        )

        if existing_user is not None:
            raise UserAlreadyExistsError("username")

        password_hash = await run_in_threadpool(
            hash_password,
            data.password
        )

        user = User(
            username=data.username,
            email=str(data.email),
            password_hash=password_hash,
            role="user",
            is_active=True
        )

        try:
            return await self.repository.create(user)

        except DuplicateKeyError as exc:    
            raise UserAlreadyExistsError(
                "email_or_username"
            ) from exc
