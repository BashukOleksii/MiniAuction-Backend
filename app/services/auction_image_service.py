import logging

from app.core.image_storage import CloudinaryImageStorage, ImageStorageError
from app.models.auction import Auction, AuctionImage
from app.models.user import User
from app.repositories.auction_image_repository import AuctionImageRepository
from app.services.auction_service import (
    AuctionConflictError,
    AuctionForbiddenError,
    AuctionNotFoundError,
)

logger = logging.getLogger(__name__)
MAX_AUCTION_IMAGES = 10
MAX_IMAGE_BYTES = 5 * 1024 * 1024


class AuctionImageDataError(Exception):
    """The submitted image or identifiers are invalid."""


class AuctionImageNotFoundError(Exception):
    """The requested public_id is not part of this auction."""


def image_extension(data: bytes, content_type: str | None) -> str:
    """Check content type against an actual file signature (never accept SVG)."""
    signatures = {
        "image/jpeg": ("jpg", data.startswith(b"\xff\xd8\xff")),
        "image/png": ("png", data.startswith(b"\x89PNG\r\n\x1a\n")),
        "image/webp": (
            "webp",
            data.startswith(b"RIFF") and data[8:12] == b"WEBP",
        ),
    }
    matched = signatures.get(content_type or "")
    if matched is None or not matched[1]:
        raise AuctionImageDataError("Only genuine JPEG, PNG or WebP images are allowed")
    return matched[0]


class AuctionImageService:
    def __init__(
        self,
        repository: AuctionImageRepository,
        storage: CloudinaryImageStorage,
    ):
        self.repository = repository
        self.storage = storage

    async def _editable(self, auction_id: str, owner: User) -> Auction:
        auction = await self.repository.get_by_id(auction_id)
        if auction is None:
            raise AuctionNotFoundError
        if auction.seller_id != owner.id:
            raise AuctionForbiddenError
        if auction.status != "draft":
            raise AuctionConflictError("Images can be changed only in a draft")
        return auction

    async def upload(
        self,
        *,
        auction_id: str,
        owner: User,
        content_type: str | None,
        contents: bytes,
    ) -> Auction:
        if not contents or len(contents) > MAX_IMAGE_BYTES:
            raise AuctionImageDataError("Image must be between 1 byte and 5 MiB")
        extension = image_extension(contents, content_type)
        auction = await self._editable(auction_id, owner)
        if len(auction.images) >= MAX_AUCTION_IMAGES:
            raise AuctionConflictError("An auction may have at most 10 images")

        public_id, url = await self.storage.upload_image(
            auction_id=auction_id, contents=contents, extension=extension
        )
        new_images = [
            *auction.images,
            AuctionImage(
                public_id=public_id,
                url=url,
                is_cover=not auction.images,
                sort_order=len(auction.images),
            ),
        ]
        try:
            updated = await self.repository.replace_draft_images(
                auction_id=auction_id,
                seller_id=owner.id,
                expected_images=auction.images,
                new_images=new_images,
            )
        except Exception:
            await self._cleanup_failed_upload(public_id)
            raise
        if updated is None:
            await self._cleanup_failed_upload(public_id)
            raise AuctionConflictError("Auction images changed; reload and try again")
        return updated

    async def _cleanup_failed_upload(self, public_id: str) -> None:
        try:
            await self.storage.delete_image(public_id=public_id)
        except ImageStorageError:
            logger.exception("Orphaned Cloudinary image requires cleanup: %s", public_id)

    async def remove(self, *, auction_id: str, owner: User, public_id: str) -> Auction:
        auction = await self._editable(auction_id, owner)
        removed = next((img for img in auction.images if img.public_id == public_id), None)
        if removed is None:
            raise AuctionImageNotFoundError
        remaining = [img for img in auction.images if img.public_id != public_id]
        new_images = [
            img.model_copy(update={
                "sort_order": index,
                "is_cover": img.is_cover or (removed.is_cover and index == 0),
            })
            for index, img in enumerate(remaining)
        ]
        updated = await self.repository.replace_draft_images(
            auction_id=auction_id,
            seller_id=owner.id,
            expected_images=auction.images,
            new_images=new_images,
        )
        if updated is None:
            raise AuctionConflictError("Auction images changed; reload and try again")
        # MongoDB first: a failed remote delete never leaves a live DB reference
        # pointing at a deleted image. Failed Cloudinary deletes need cleanup.
        try:
            await self.storage.delete_image(public_id=public_id)
        except ImageStorageError:
            logger.exception("Orphaned Cloudinary image requires cleanup: %s", public_id)
        return updated

    async def set_cover(
        self, *, auction_id: str, owner: User, public_id: str
    ) -> Auction:
        auction = await self._editable(auction_id, owner)
        if not any(img.public_id == public_id for img in auction.images):
            raise AuctionImageNotFoundError
        new_images = [
            img.model_copy(update={"is_cover": img.public_id == public_id})
            for img in auction.images
        ]
        updated = await self.repository.replace_draft_images(
            auction_id=auction_id,
            seller_id=owner.id,
            expected_images=auction.images,
            new_images=new_images,
        )
        if updated is None:
            raise AuctionConflictError("Auction images changed; reload and try again")
        return updated

    async def reorder(
        self, *, auction_id: str, owner: User, public_ids: list[str]
    ) -> Auction:
        auction = await self._editable(auction_id, owner)
        existing = {img.public_id: img for img in auction.images}
        if len(public_ids) != len(existing) or set(public_ids) != set(existing):
            raise AuctionImageDataError("Supply every image public_id exactly once")
        new_images = [
            existing[public_id].model_copy(update={"sort_order": index})
            for index, public_id in enumerate(public_ids)
        ]
        updated = await self.repository.replace_draft_images(
            auction_id=auction_id,
            seller_id=owner.id,
            expected_images=auction.images,
            new_images=new_images,
        )
        if updated is None:
            raise AuctionConflictError("Auction images changed; reload and try again")
        return updated
