from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from pymongo.asynchronous.database import AsyncDatabase

from app.core.security import decode_access_token
from app.db.mongodb import get_database
from app.models.user import User
from app.repositories.user_repository import UserRepository

bearer_scheme = HTTPBearer(auto_error=False)


def get_user_repository(
    db: Annotated[AsyncDatabase, Depends(get_database)],
) -> UserRepository:
    return UserRepository(db)


async def get_current_user(
    repository: Annotated[UserRepository, Depends(get_user_repository)],
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized
    try:
        payload = decode_access_token(credentials.credentials)
    except InvalidTokenError as exc:
        raise unauthorized from exc
    user = await repository.get_by_id(payload["sub"])
    if user is None or not user.is_active:
        raise unauthorized
    if payload.get("ver", 0) != user.token_version:
        raise unauthorized
    return user
