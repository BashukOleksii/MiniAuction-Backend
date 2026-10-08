from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pymongo.asynchronous.database import AsyncDatabase

from app.api.admin_dependencies import get_current_admin
from app.db.mongodb import get_database
from app.models.common import utc_now
from app.models.user import User
from app.repositories.admin_repository import AdminRepository
from app.schemas.admin import (
    AdminAuctionPage,
    AdminAuditPage,
    AdminStatistics,
    AdminUserPage,
    AdminUserResponse,
    ModerationReason,
)
from app.schemas.auction import AuctionResponse
from app.services.admin_service import (
    AdminConflictError,
    AdminNotFoundError,
    AdminService,
)
from app.services.auction_service import auction_response

router = APIRouter()


def get_admin_repository(
    db: Annotated[AsyncDatabase, Depends(get_database)],
) -> AdminRepository:
    return AdminRepository(db)


def _error(exc: Exception) -> None:
    if isinstance(exc, AdminNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, AdminConflictError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    raise exc


@router.get("/users", response_model=AdminUserPage)
async def list_users(
    admin: Annotated[User, Depends(get_current_admin)],
    repository: Annotated[AdminRepository, Depends(get_admin_repository)],
    search: Annotated[str | None, Query(max_length=100)] = None,
    role: Annotated[Literal["user", "admin"] | None, Query()] = None,
    is_active: Annotated[bool | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AdminUserPage:
    return await AdminService(repository).list_users(
        search=search, role=role, active=is_active, page=page, page_size=page_size
    )


@router.get("/users/{user_id}", response_model=AdminUserResponse)
async def get_user(
    user_id: str,
    admin: Annotated[User, Depends(get_current_admin)],
    repository: Annotated[AdminRepository, Depends(get_admin_repository)],
) -> AdminUserResponse:
    try:
        return await AdminService(repository).get_user(user_id)
    except AdminNotFoundError as exc:
        _error(exc)
        raise AssertionError("Unreachable") from exc


@router.post("/users/{user_id}/block", response_model=AdminUserResponse)
async def block_user(
    user_id: str,
    data: ModerationReason,
    admin: Annotated[User, Depends(get_current_admin)],
    repository: Annotated[AdminRepository, Depends(get_admin_repository)],
) -> AdminUserResponse:
    try:
        return await AdminService(repository).set_user_active(
            admin=admin, user_id=user_id, is_active=False, reason=data.reason
        )
    except (AdminNotFoundError, AdminConflictError) as exc:
        _error(exc)
        raise AssertionError("Unreachable") from exc


@router.post("/users/{user_id}/unblock", response_model=AdminUserResponse)
async def unblock_user(
    user_id: str,
    data: ModerationReason,
    admin: Annotated[User, Depends(get_current_admin)],
    repository: Annotated[AdminRepository, Depends(get_admin_repository)],
) -> AdminUserResponse:
    try:
        return await AdminService(repository).set_user_active(
            admin=admin, user_id=user_id, is_active=True, reason=data.reason
        )
    except (AdminNotFoundError, AdminConflictError) as exc:
        _error(exc)
        raise AssertionError("Unreachable") from exc


@router.get("/auctions", response_model=AdminAuctionPage)
async def list_auctions(
    admin: Annotated[User, Depends(get_current_admin)],
    repository: Annotated[AdminRepository, Depends(get_admin_repository)],
    state: Annotated[
        Literal["draft", "scheduled", "active", "finished", "cancelled"] | None,
        Query(alias="status"),
    ] = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
    seller_id: Annotated[str | None, Query(min_length=1)] = None,
    category: Annotated[str | None, Query(min_length=2, max_length=80)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AdminAuctionPage:
    return await AdminService(repository).list_auctions(
        state=state, search=search, seller_id=seller_id,
        category=category, page=page, page_size=page_size,
    )


@router.get("/auctions/{auction_id}", response_model=AuctionResponse)
async def get_auction(
    auction_id: str,
    admin: Annotated[User, Depends(get_current_admin)],
    repository: Annotated[AdminRepository, Depends(get_admin_repository)],
) -> AuctionResponse:
    try:
        auction = await AdminService(repository).get_auction(auction_id)
    except AdminNotFoundError as exc:
        _error(exc)
        raise AssertionError("Unreachable") from exc
    return auction_response(auction, utc_now())


@router.post("/auctions/{auction_id}/cancel", response_model=AuctionResponse)
async def cancel_auction(
    auction_id: str,
    data: ModerationReason,
    admin: Annotated[User, Depends(get_current_admin)],
    repository: Annotated[AdminRepository, Depends(get_admin_repository)],
) -> AuctionResponse:
    try:
        auction = await AdminService(repository).cancel_auction(
            admin=admin, auction_id=auction_id, reason=data.reason
        )
    except (AdminNotFoundError, AdminConflictError) as exc:
        _error(exc)
        raise AssertionError("Unreachable") from exc
    return auction_response(auction, utc_now())


@router.get("/statistics", response_model=AdminStatistics)
async def statistics(
    admin: Annotated[User, Depends(get_current_admin)],
    repository: Annotated[AdminRepository, Depends(get_admin_repository)],
) -> AdminStatistics:
    return await AdminService(repository).statistics()


@router.get("/audit-logs", response_model=AdminAuditPage)
async def audit_logs(
    admin: Annotated[User, Depends(get_current_admin)],
    repository: Annotated[AdminRepository, Depends(get_admin_repository)],
    action: Annotated[
        Literal["user.block", "user.unblock", "auction.cancel"] | None, Query()
    ] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AdminAuditPage:
    return await AdminService(repository).audit_logs(
        action=action, page=page, page_size=page_size
    )
