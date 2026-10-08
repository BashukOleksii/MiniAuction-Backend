from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_user_repository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse
from app.schemas.user import UserResponse
from app.services.auth_service import (
    AuthService,
    InvalidCredentialsError,
    UserAlreadyExistsError,
)

router = APIRouter()


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_user(
    data: RegisterRequest,
    repository: Annotated[UserRepository, Depends(get_user_repository)],
) -> UserResponse:
    try:
        user = await AuthService(repository).register(data)
    except UserAlreadyExistsError as exc:
        messages = {
            "email": "Email is already registered",
            "username": "Username is already taken",
            "email_or_username": "Email or username is already in use",
        }
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=messages.get(exc.field, "User already exists"),
        ) from exc
    return UserResponse.model_validate(user)


@router.post("/login", response_model=TokenResponse)
async def login_user(
    data: LoginRequest,
    repository: Annotated[UserRepository, Depends(get_user_repository)],
) -> TokenResponse:
    try:
        token = await AuthService(repository).login(data)
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return TokenResponse(access_token=token)
