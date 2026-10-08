from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_user_repository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import RegisterRequest
from app.schemas.user import UserResponse
from app.services.auth_service import (
    AuthService,
    UserAlreadyExistsError,
)

router = APIRouter()


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED
)
async def register_user(
    data: RegisterRequest,
    repository: Annotated[
        UserRepository,
        Depends(get_user_repository)
    ]
) -> UserResponse:

    service = AuthService(repository)

    try:
        user = await service.register(data)

    except UserAlreadyExistsError as exc:
        messages = {
            "email": "Email is already registered",
            "username": "Username is already taken",
            "email_or_username": "Email or username is already in use"
        }

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=messages.get(
                exc.field,
                "User already exists"
            )
        ) from exc

    return UserResponse.model_validate(user)
