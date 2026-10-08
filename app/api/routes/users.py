from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.dependencies import get_current_user, get_user_repository
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.user import (
    ChangePasswordRequest,
    PublicUserResponse,
    UpdateProfileRequest,
    UserResponse,
)
from app.services.auth_service import UserAlreadyExistsError
from app.services.user_service import (
    InvalidCurrentPasswordError,
    SamePasswordError,
    UserNotFoundError,
    UserService,
)

router = APIRouter()


@router.get("/me", response_model=UserResponse)
async def get_my_profile(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserResponse:
    return UserResponse.model_validate(current_user)


@router.patch("/me", response_model=UserResponse)
async def update_my_profile(
    data: UpdateProfileRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    repository: Annotated[UserRepository, Depends(get_user_repository)],
) -> UserResponse:
    try:
        user = await UserService(repository).update_profile(current_user, data)
    except UserAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Profile field is already in use: {exc.field}",
        ) from exc
    except UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail="User not found") from exc
    return UserResponse.model_validate(user)


@router.patch("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_my_password(
    data: ChangePasswordRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    repository: Annotated[UserRepository, Depends(get_user_repository)],
) -> Response:
    try:
        await UserService(repository).change_password(current_user, data)
    except InvalidCurrentPasswordError as exc:
        raise HTTPException(status_code=400, detail="Incorrect current password") from exc
    except SamePasswordError as exc:
        raise HTTPException(status_code=400, detail="New password must differ") from exc
    except UserNotFoundError as exc:
        raise HTTPException(status_code=409, detail="Profile was changed concurrently") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{user_id}", response_model=PublicUserResponse)
async def get_public_user(
    user_id: str,
    repository: Annotated[UserRepository, Depends(get_user_repository)],
) -> PublicUserResponse:
    try:
        user = await UserService(repository).get_public_user(user_id)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail="User not found") from exc
    return PublicUserResponse.model_validate(user)
