from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from app.core.security import decode_access_token
from app.db.mongodb import get_database
from app.models.user import User

# Репозиторії
from app.repositories.auction_finalization_repository import AuctionFinalizationRepository
from app.repositories.auction_repository import AuctionRepository
from app.repositories.bid_repository import BidRepository
from app.repositories.user_repository import UserRepository

# Сервіси
from app.services.auction_finalization_service import AuctionFinalizationService
from app.services.auction_state_service import AuctionStateService
from app.services.bid_service import BidService

bearer_scheme = HTTPBearer(auto_error=False)


# ==============================================================================
# Базові клієнти та репозиторії
# ==============================================================================
def get_mongo_client(request: Request) -> AsyncMongoClient:
    """Отримує зареєстрований асинхронний клієнт MongoDB зі стану застосунку."""
    return request.app.state.mongo_client


def get_user_repository(
    db: Annotated[AsyncDatabase, Depends(get_database)],
) -> UserRepository:
    return UserRepository(db)


def get_auction_repository(
    db: Annotated[AsyncDatabase, Depends(get_database)],
) -> AuctionRepository:
    return AuctionRepository(db)


# Аліас для сумісності з роутами першого розробника
get_auction_repo = get_auction_repository


def get_bid_repository(
    db: Annotated[AsyncDatabase, Depends(get_database)],
) -> BidRepository:
    return BidRepository(db)


def get_auction_finalization_repository(
    db: Annotated[AsyncDatabase, Depends(get_database)],
) -> AuctionFinalizationRepository:
    return AuctionFinalizationRepository(db)


# ==============================================================================
# Автентифікація
# ==============================================================================
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


async def get_optional_current_user(
    repository: Annotated[UserRepository, Depends(get_user_repository)],
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
) -> User | None:
    """Для публічних сторінок та polling: повертає None для гостя замість 401."""
    if credentials is None:
        return None
    try:
        return await get_current_user(repository, credentials)
    except HTTPException:
        return None


# ==============================================================================
# Сервіси (Bidding, Polling, State, Finalization)
# ==============================================================================
def get_bid_service(
    client: Annotated[AsyncMongoClient, Depends(get_mongo_client)],
    bid_repo: Annotated[BidRepository, Depends(get_bid_repository)],
    auction_repo: Annotated[AuctionRepository, Depends(get_auction_repository)],
) -> BidService:
    return BidService(
        mongo_client=client,
        bid_repo=bid_repo,
        auction_repo=auction_repo,
    )


def get_auction_finalization_service(
    auction_repo: Annotated[AuctionRepository, Depends(get_auction_repository)],
    finalization_repo: Annotated[
        AuctionFinalizationRepository, Depends(get_auction_finalization_repository)
    ],
) -> AuctionFinalizationService:
    return AuctionFinalizationService(
        auction_repo=auction_repo,
        finalization_repo=finalization_repo,
    )


def get_auction_state_service(
    auction_repo: Annotated[AuctionRepository, Depends(get_auction_repository)],
    bid_repo: Annotated[BidRepository, Depends(get_bid_repository)],
    finalization_service: Annotated[
        AuctionFinalizationService, Depends(get_auction_finalization_service)
    ],
) -> AuctionStateService:
    return AuctionStateService(
        auction_repo=auction_repo,
        bid_repo=bid_repo,
        finalization_service=finalization_service,
    )