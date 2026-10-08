from pymongo.errors import DuplicateKeyError
from starlette.concurrency import run_in_threadpool

from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.auth import LoginRequest, RegisterRequest


class UserAlreadyExistsError(Exception):
    def __init__(self, field: str):
        self.field = field
        super().__init__(f"User conflict: {field}")


class InvalidCredentialsError(Exception):
    pass


class AuthService:
    def __init__(self, repository: UserRepository):
        self.repository = repository

    async def register(self, data: RegisterRequest) -> User:
        if await self.repository.get_by_email(str(data.email)) is not None:
            raise UserAlreadyExistsError("email")
        if await self.repository.get_by_username(data.username) is not None:
            raise UserAlreadyExistsError("username")

        password_hash = await run_in_threadpool(hash_password, data.password)
        user = User(
            username=data.username,
            email=str(data.email),
            password_hash=password_hash,
            role="user",
            is_active=True,
        )
        try:
            return await self.repository.create(user)
        except DuplicateKeyError as exc:
            raise UserAlreadyExistsError("email_or_username") from exc

    async def login(self, data: LoginRequest) -> str:
        user = await self.repository.get_by_email(str(data.email))
        if user is None or not user.is_active:
            raise InvalidCredentialsError
        correct = await run_in_threadpool(
            verify_password, data.password, user.password_hash
        )
        if not correct:
            raise InvalidCredentialsError
        return create_access_token(
            user_id=user.id,
            role=user.role,
            token_version=user.token_version,
        )
