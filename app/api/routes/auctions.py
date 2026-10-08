"""Auctions REST routes. Bidding remains in the other developer's module."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pymongo.asynchronous.database import AsyncDatabase

from app.api.dependencies import get_current_user, get_optional_current_user
from app.db.mongodb import get_database
from app.models.common import utc_now
from app.models.user import User
from app.repositories.auction_repository import AuctionRepository
from app.schemas.auction import (
    AUCTION_CATEGORIES,
    AuctionCreateRequest,
    AuctionPage,
    AuctionResponse,
    AuctionUpdateRequest,
)
from app.services.auction_service import (
    AuctionConflictError,
    AuctionDataError,
    AuctionForbiddenError,
    AuctionNotFoundError,
    AuctionService,
    auction_response,
)

router = APIRouter()
my_router = APIRouter()


def get_auction_repository(
    db: Annotated[AsyncDatabase, Depends(get_database)],
) -> AuctionRepository:
    return AuctionRepository(db)


def _raise_http_error(exc: Exception) -> None:
    if isinstance(exc, AuctionNotFoundError):
        raise HTTPException(status_code=404, detail="Auction not found") from exc
    if isinstance(exc, AuctionForbiddenError):
        raise HTTPException(status_code=403, detail="Not an auction owner") from exc
    if isinstance(exc, AuctionDataError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if isinstance(exc, AuctionConflictError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    raise exc


@router.get("/categories", response_model=list[str])
async def auction_categories() -> list[str]:
    return list(AUCTION_CATEGORIES)


@router.get("", response_model=AuctionPage)
@router.get("/", response_model=AuctionPage, include_in_schema=False)
async def list_auctions(
    repository: Annotated[AuctionRepository, Depends(get_auction_repository)],
    search: Annotated[str | None, Query(max_length=100)] = None,
    category: Annotated[str | None, Query(min_length=2, max_length=80)] = None,
    min_price: Annotated[int | None, Query(ge=0)] = None,
    max_price: Annotated[int | None, Query(ge=0)] = None,
    status_filter: Annotated[
        Literal["active", "scheduled", "finished"], Query(alias="status")
    ] = "active",
    sort_by: Annotated[
        Literal["created_at", "current_price", "ends_at", "title"], Query()
    ] = "ends_at",
    sort_order: Annotated[Literal["asc", "desc"], Query()] = "asc",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AuctionPage:
    try:
        return await AuctionService(repository).list_public(
            availability=status_filter,
            search=search,
            category=category,
            min_price=min_price,
            max_price=max_price,
            sort_by=sort_by,
            sort_order=sort_order,
            page=page,
            page_size=page_size,
        )
    except AuctionDataError as exc:
        _raise_http_error(exc)
        raise AssertionError("Unreachable") from exc


@router.post("", response_model=AuctionResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=AuctionResponse, status_code=status.HTTP_201_CREATED, include_in_schema=False)
async def create_auction(
    data: AuctionCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    repository: Annotated[AuctionRepository, Depends(get_auction_repository)],
) -> AuctionResponse:
    try:
        auction = await AuctionService(repository).create(data, current_user)
    except AuctionDataError as exc:
        _raise_http_error(exc)
        raise AssertionError("Unreachable") from exc
    return auction_response(auction, utc_now())


@my_router.get("/auctions", response_model=AuctionPage)
async def my_auctions(
    current_user: Annotated[User, Depends(get_current_user)],
    repository: Annotated[AuctionRepository, Depends(get_auction_repository)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AuctionPage:
    return await AuctionService(repository).list_by_seller(current_user, page, page_size)


@router.get("/{auction_id}", response_model=AuctionResponse)
async def get_auction(
    auction_id: str,
    current_user: Annotated[User | None, Depends(get_optional_current_user)],
    repository: Annotated[AuctionRepository, Depends(get_auction_repository)],
) -> AuctionResponse:
    try:
        auction = await AuctionService(repository).get(auction_id, current_user)
    except AuctionNotFoundError as exc:
        _raise_http_error(exc)
        raise AssertionError("Unreachable") from exc
    return auction_response(auction, utc_now())


@router.patch("/{auction_id}", response_model=AuctionResponse)
async def update_auction(
    auction_id: str,
    data: AuctionUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    repository: Annotated[AuctionRepository, Depends(get_auction_repository)],
) -> AuctionResponse:
    try:
        auction = await AuctionService(repository).update(auction_id, data, current_user)
    except (AuctionNotFoundError, AuctionForbiddenError, AuctionConflictError, AuctionDataError) as exc:
        _raise_http_error(exc)
        raise AssertionError("Unreachable") from exc
    return auction_response(auction, utc_now())


@router.post("/{auction_id}/publish", response_model=AuctionResponse)
async def publish_auction(
    auction_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    repository: Annotated[AuctionRepository, Depends(get_auction_repository)],
) -> AuctionResponse:
    try:
        auction = await AuctionService(repository).publish(auction_id, current_user)
    except (AuctionNotFoundError, AuctionForbiddenError, AuctionConflictError) as exc:
        _raise_http_error(exc)
        raise AssertionError("Unreachable") from exc
    return auction_response(auction, utc_now())


@router.post("/{auction_id}/cancel", response_model=AuctionResponse)
async def cancel_auction(
    auction_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    repository: Annotated[AuctionRepository, Depends(get_auction_repository)],
) -> AuctionResponse:
    try:
        auction = await AuctionService(repository).cancel(auction_id, current_user)
    except (AuctionNotFoundError, AuctionForbiddenError, AuctionConflictError) as exc:
        _raise_http_error(exc)
        raise AssertionError("Unreachable") from exc
    return auction_response(auction, utc_now())
