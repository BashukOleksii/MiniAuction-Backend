"""Small Cloudinary adapter tests, stubbing the network SDK only."""

import cloudinary.uploader
import pytest

from app.core.image_storage import CloudinaryImageStorage, ImageStorageError


@pytest.mark.asyncio
async def test_cloudinary_upload_uses_image_mode_and_secure_url(monkeypatch):
    def fake_upload(stream, **options):
        assert stream.read().startswith(b"\x89PNG")
        assert options["resource_type"] == "image"
        assert options["folder"] == "mini_auction/auctions/lot1"
        assert options["overwrite"] is False
        return {
            "public_id": "mini_auction/auctions/lot1/photo1",
            "secure_url": "https://res.cloudinary.com/demo/image/upload/photo1.png",
        }

    monkeypatch.setattr(cloudinary.uploader, "upload", fake_upload, raising=False)
    storage = CloudinaryImageStorage()
    public_id, url = await storage.upload_image(
        auction_id="lot1", contents=b"\x89PNG123", extension="png"
    )
    assert public_id.endswith("photo1")
    assert url.startswith("https://")


@pytest.mark.asyncio
async def test_cloudinary_delete_calls_invalidation(monkeypatch):
    called = []

    def fake_destroy(public_id, **options):
        called.append((public_id, options))
        return {"result": "ok"}

    monkeypatch.setattr(cloudinary.uploader, "destroy", fake_destroy, raising=False)
    await CloudinaryImageStorage().delete_image(public_id="auction/photo1")
    assert called == [("auction/photo1", {"resource_type": "image", "invalidate": True})]


@pytest.mark.asyncio
async def test_cloudinary_missing_https_url_is_rejected(monkeypatch):
    def fake_upload(stream, **options):
        return {"public_id": "photo1", "secure_url": "http://invalid"}

    monkeypatch.setattr(cloudinary.uploader, "upload", fake_upload, raising=False)
    with pytest.raises(ImageStorageError):
        await CloudinaryImageStorage().upload_image(
            auction_id="lot1", contents=b"abc", extension="png"
        )
