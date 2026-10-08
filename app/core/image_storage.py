import logging
from io import BytesIO
from uuid import uuid4

import cloudinary.uploader
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)


class ImageStorageError(Exception):
    """An upload or deletion failed at the storage provider."""


class CloudinaryImageStorage:
    async def upload_image(
        self, *, auction_id: str, contents: bytes, extension: str
    ) -> tuple[str, str]:
        # Auction IDs originate from the application, not arbitrary paths.
        stream = BytesIO(contents)
        stream.name = f"photo.{extension}"
        try:
            result = await run_in_threadpool(
                cloudinary.uploader.upload,
                stream,
                folder=f"mini_auction/auctions/{auction_id}",
                public_id=uuid4().hex,
                overwrite=False,
                resource_type="image",
            )
            public_id = result.get("public_id")
            secure_url = result.get("secure_url")
            if not isinstance(public_id, str) or not public_id:
                raise ImageStorageError("Storage provider returned no image identifier")
            if not isinstance(secure_url, str) or not secure_url.startswith("https://"):
                raise ImageStorageError("Storage provider returned no secure image URL")
            return public_id, secure_url
        except ImageStorageError:
            raise
        except Exception as exc:
            logger.exception("Cloudinary upload failed")
            raise ImageStorageError("Image upload failed") from exc

    async def delete_image(self, *, public_id: str) -> None:
        try:
            result = await run_in_threadpool(
                cloudinary.uploader.destroy,
                public_id,
                resource_type="image",
                invalidate=True,
            )
            if result.get("result") not in ("ok", "not found"):
                raise ImageStorageError("Storage provider could not delete image")
        except ImageStorageError:
            raise
        except Exception as exc:
            logger.exception("Cloudinary delete failed")
            raise ImageStorageError("Image deletion failed") from exc


def get_image_storage() -> CloudinaryImageStorage:
    return CloudinaryImageStorage()
