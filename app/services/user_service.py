
from pymongo.errors import DuplicateKeyError
from starlette.concurrency import run_in_threadpool

from app.core.security import hash_password, verify_password
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.user import ChangePasswordRequest, UpdateProfileRequest
from app.services.auth_service import UserAlreadyExistsError


class UserNotFoundError(Exception):
    pass


class InvalidCurrentPasswordError(Exception):
    pass


class SamePasswordError(Exception):
    pass


class UserService:
    def __init__(self, repository: UserRepository):
        self.repository = repository

    async def get_public_user(self, user_id: str) -> User:
        user = await self.repository.get_by_id(user_id)

        if user is None or not user.is_active:
            raise UserNotFoundError

        return user

    async def update_profile(
        self,
        current_user: User,
        data: UpdateProfileRequest
    ) -> User:
        changes = data.model_dump(exclude_unset=True)

        new_email = changes.get("email")
        new_username = changes.get("username")

        if (
            new_email is not None
            and new_email != str(current_user.email)
            and await self.repository.get_by_email(new_email) is not None
        ):
            raise UserAlreadyExistsError("email")

        if (
            new_username is not None
            and new_username != current_user.username
            and await self.repository.get_by_username(new_username) is not None
        ):
            raise UserAlreadyExistsError("username")

        try:
            updated = await self.repository.update_profile(
                current_user.id,
                changes
            )

        except DuplicateKeyError as exc:
            raise UserAlreadyExistsError(
                "email_or_username"
            ) from exc

        if updated is None:
            raise UserNotFoundError

        return updated

    async def change_password(
        self,
        current_user: User,
        data: ChangePasswordRequest
    ) -> None:
        valid = await run_in_threadpool(
            verify_password,
            data.current_password,
            current_user.password_hash
        )

        if not valid:
            raise InvalidCurrentPasswordError

        if data.current_password == data.new_password:
            raise SamePasswordError

        new_hash = await run_in_threadpool(
            hash_password,
            data.new_password
        )
        updated = await self.repository.update_password(
            user_id=current_user.id,
            expected_hash=current_user.password_hash,
            new_password_hash=new_hash
        )

        if updated is None:
            raise UserNotFoundError
