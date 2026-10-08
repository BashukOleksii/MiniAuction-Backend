from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pymongo.asynchronous.database import AsyncDatabase

from app.api.dependencies import get_current_user
from app.core.image_storage import (
    CloudinaryImageStorage,
    ImageStorageError,
    get_image_storage,
)
from app.db.mongodb import get_database
from app.models.common import utc_now
from app.models.user import User
from app.repositories.auction_image_repository import AuctionImageRepository
from app.schemas.auction import AuctionResponse
from app.schemas.auction_images import (
    ReorderAuctionImagesRequest,
    SetAuctionCoverRequest,
)
from app.services.auction_image_service import (
    MAX_IMAGE_BYTES,
    AuctionImageDataError,
    AuctionImageNotFoundError,
    AuctionImageService,
)
from app.services.auction_service import (
    AuctionConflictError,
    AuctionForbiddenError,
    AuctionNotFoundError,
    auction_response,
)

router = APIRouter()


def get_auction_image_repository(
    db: Annotated[AsyncDatabase, Depends(get_database)],
) -> AuctionImageRepository:
    return AuctionImageRepository(db)


def _raise_image_error(exc: Exception) -> None:
    if isinstance(exc, (AuctionNotFoundError, AuctionImageNotFoundError)):
        raise HTTPException(status_code=404, detail="Auction or image not found") from exc
    if isinstance(exc, AuctionForbiddenError):
        raise HTTPException(status_code=403, detail="Not an auction owner") from exc
    if isinstance(exc, AuctionConflictError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, AuctionImageDataError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if isinstance(exc, ImageStorageError):
        raise HTTPException(status_code=502, detail="Image storage is unavailable") from exc
    raise exc


@router.post(
    "/{auction_id}/images",
    response_model=AuctionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_auction_image(
    auction_id: str,
    file: Annotated[UploadFile, File(description="JPEG, PNG or WebP, maximum 5 MiB")],
    owner: Annotated[User, Depends(get_current_user)],
    repository: Annotated[
        AuctionImageRepository, Depends(get_auction_image_repository)
    ],
    storage: Annotated[CloudinaryImageStorage, Depends(get_image_storage)],
) -> AuctionResponse:
    try:
        contents = await file.read(MAX_IMAGE_BYTES + 1)
    finally:
        await file.close()
    try:
        auction = await AuctionImageService(repository, storage).upload(
            auction_id=auction_id,
            owner=owner,
            content_type=file.content_type,
            contents=contents,
        )
    except (
        AuctionNotFoundError,
        AuctionForbiddenError,
        AuctionConflictError,
        AuctionImageDataError,
        ImageStorageError,
    ) as exc:
        _raise_image_error(exc)
        raise AssertionError("Unreachable") from exc
    return auction_response(auction, utc_now())


@router.delete("/{auction_id}/images", response_model=AuctionResponse)
async def delete_auction_image(
    auction_id: str,
    public_id: Annotated[str, Query(min_length=1)],
    owner: Annotated[User, Depends(get_current_user)],
    repository: Annotated[
        AuctionImageRepository, Depends(get_auction_image_repository)
    ],
    storage: Annotated[CloudinaryImageStorage, Depends(get_image_storage)],
) -> AuctionResponse:
    try:
        auction = await AuctionImageService(repository, storage).remove(
            auction_id=auction_id, owner=owner, public_id=public_id
        )
    except (
        AuctionNotFoundError,
        AuctionForbiddenError,
        AuctionConflictError,
        AuctionImageNotFoundError,
    ) as exc:
        _raise_image_error(exc)
        raise AssertionError("Unreachable") from exc
    return auction_response(auction, utc_now())


@router.patch("/{auction_id}/images/cover", response_model=AuctionResponse)
async def change_auction_cover(
    auction_id: str,
    data: SetAuctionCoverRequest,
    owner: Annotated[User, Depends(get_current_user)],
    repository: Annotated[
        AuctionImageRepository, Depends(get_auction_image_repository)
    ],
    storage: Annotated[CloudinaryImageStorage, Depends(get_image_storage)],
) -> AuctionResponse:
    try:
        auction = await AuctionImageService(repository, storage).set_cover(
            auction_id=auction_id, owner=owner, public_id=data.public_id
        )
    except (
        AuctionNotFoundError,
        AuctionForbiddenError,
        AuctionConflictError,
        AuctionImageNotFoundError,
    ) as exc:
        _raise_image_error(exc)
        raise AssertionError("Unreachable") from exc
    return auction_response(auction, utc_now())


@router.patch("/{auction_id}/images/order", response_model=AuctionResponse)
async def reorder_auction_images(
    auction_id: str,
    data: ReorderAuctionImagesRequest,
    owner: Annotated[User, Depends(get_current_user)],
    repository: Annotated[
        AuctionImageRepository, Depends(get_auction_image_repository)
    ],
    storage: Annotated[CloudinaryImageStorage, Depends(get_image_storage)],
) -> AuctionResponse:
    try:
        auction = await AuctionImageService(repository, storage).reorder(
            auction_id=auction_id, owner=owner, public_ids=data.public_ids
        )
    except (
        AuctionNotFoundError,
        AuctionForbiddenError,
        AuctionConflictError,
        AuctionImageDataError,
    ) as exc:
        _raise_image_error(exc)
        raise AssertionError("Unreachable") from exc
    return auction_response(auction, utc_now())
