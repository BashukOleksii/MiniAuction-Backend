"""API-level image tests: no real MongoDB or Cloudinary network calls."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_user
from app.api.routes.auction_images import get_auction_image_repository
from app.core.image_storage import get_image_storage
from app.main import app
from app.models.auction import Auction, AuctionImage
from app.models.common import utc_now
from app.models.user import User

PNG = b"\x89PNG\r\n\x1a\n" + b"test image bytes"
JPEG = b"\xff\xd8\xff" + b"test image bytes"
WEBP = b"RIFF" + b"1234WEBP" + b"test image bytes"


class FakeImageRepository:
    def __init__(self, auction: Auction):
        self.auction = auction
        self.fail_cas = False
        self.change_status_at_cas = False

    async def get_by_id(self, auction_id: str) -> Auction | None:
        return self.auction if auction_id == self.auction.id else None

    async def replace_draft_images(
        self, *, auction_id, seller_id, expected_images, new_images
    ) -> Auction | None:
        if self.change_status_at_cas:
            self.auction.status = "active"
        if (
            self.fail_cas
            or auction_id != self.auction.id
            or seller_id != self.auction.seller_id
            or self.auction.status != "draft"
            or self.auction.images != expected_images
        ):
            return None
        self.auction.images = new_images
        self.auction.updated_at = utc_now()
        return self.auction


class FakeStorage:
    def __init__(self):
        self.uploads: list[tuple[str, str]] = []
        self.deleted: list[str] = []

    async def upload_image(self, *, auction_id, contents, extension):
        assert auction_id and contents
        public_id = f"mini_auction/auctions/{auction_id}/img{len(self.uploads) + 1}"
        self.uploads.append((public_id, extension))
        return public_id, f"https://res.cloudinary.com/demo/{public_id}.jpg"

    async def delete_image(self, *, public_id):
        self.deleted.append(public_id)


@pytest.fixture
def api():
    owner = User(username="Seller", email="seller@example.com", password_hash="hash")
    other = User(username="Someone", email="someone@example.com", password_hash="hash")
    auction = Auction(
        seller_id=owner.id,
        title="Keyboard",
        category="electronics",
        starting_price=100,
        current_price=100,
        ends_at=utc_now() + timedelta(days=3),
    )
    repo = FakeImageRepository(auction)
    storage = FakeStorage()
    current = {"user": owner}
    app.dependency_overrides[get_current_user] = lambda: current["user"]
    app.dependency_overrides[get_auction_image_repository] = lambda: repo
    app.dependency_overrides[get_image_storage] = lambda: storage
    # Do not enter TestClient context: lifespan would connect to MongoDB Atlas.
    client = TestClient(app)
    try:
        yield client, repo, storage, current, owner, other
    finally:
        client.close()
        app.dependency_overrides.clear()


def post_image(client: TestClient, auction_id: str, data=PNG, mime="image/png"):
    return client.post(
        f"/api/v1/auctions/{auction_id}/images",
        files={"file": ("photo.png", data, mime)},
    )


def add_image(client: TestClient, auction_id: str) -> dict:
    response = post_image(client, auction_id)
    assert response.status_code == 201, response.text
    return response.json()["images"][-1]


def test_routes_are_in_openapi():
    schema = app.openapi()
    root = "/api/v1/auctions/{auction_id}/images"
    assert "post" in schema["paths"][root]
    assert "delete" in schema["paths"][root]
    assert "patch" in schema["paths"][root + "/cover"]
    assert "patch" in schema["paths"][root + "/order"]


def test_upload_creates_first_cover_and_returns_201(api):
    client, repo, storage, *_ = api
    response = post_image(client, repo.auction.id)
    assert response.status_code == 201, response.text
    image = response.json()["images"][0]
    assert image["is_cover"] is True
    assert image["sort_order"] == 0
    assert image["url"].startswith("https://")
    assert storage.uploads[0][1] == "png"


def test_second_image_is_not_cover(api):
    client, repo, storage, *_ = api
    first = add_image(client, repo.auction.id)
    second = add_image(client, repo.auction.id)
    assert first["public_id"] != second["public_id"]
    assert repo.auction.images[0].is_cover is True
    assert repo.auction.images[1].is_cover is False
    assert repo.auction.images[1].sort_order == 1


@pytest.mark.parametrize(
    ("data", "mime"),
    [
        (b"not image", "image/png"),
        (PNG, "image/jpeg"),
        (b"<svg></svg>", "image/svg+xml"),
        (b"", "image/png"),
        (PNG, "application/octet-stream"),
        (PNG + b"x" * (5 * 1024 * 1024), "image/png"),
    ],
)
def test_rejects_bad_uploads(api, data, mime):
    client, repo, storage, *_ = api
    response = post_image(client, repo.auction.id, data=data, mime=mime)
    assert response.status_code == 422, response.text
    assert storage.uploads == []


def test_accepts_jpeg_and_webp(api):
    client, repo, storage, *_ = api
    assert post_image(client, repo.auction.id, JPEG, "image/jpeg").status_code == 201
    assert post_image(client, repo.auction.id, WEBP, "image/webp").status_code == 201
    assert [ext for _, ext in storage.uploads] == ["jpg", "webp"]


def test_non_owner_cannot_upload(api):
    client, repo, storage, current, _, other = api
    current["user"] = other
    assert post_image(client, repo.auction.id).status_code == 403
    assert storage.uploads == []


@pytest.mark.parametrize("state", ["active", "cancelled", "finished"])
def test_non_draft_cannot_upload(api, state):
    client, repo, storage, *_ = api
    repo.auction.status = state
    assert post_image(client, repo.auction.id).status_code == 409
    assert not storage.uploads


def test_missing_auction_returns_404(api):
    client, _, storage, *_ = api
    assert post_image(client, "missing-id").status_code == 404
    assert not storage.uploads


def test_cas_failure_removes_uploaded_cloudinary_image(api):
    client, repo, storage, *_ = api
    repo.fail_cas = True
    response = post_image(client, repo.auction.id)
    assert response.status_code == 409
    assert storage.deleted == [storage.uploads[0][0]]
    assert repo.auction.images == []


def test_publish_during_upload_rejects_and_cleans_up(api):
    client, repo, storage, *_ = api
    repo.change_status_at_cas = True
    assert post_image(client, repo.auction.id).status_code == 409
    assert storage.deleted == [storage.uploads[0][0]]


def test_limit_ten_images(api):
    client, repo, storage, *_ = api
    for i in range(10):
        repo.auction.images.append(
            AuctionImage(
                public_id=f"auctions/photo{i}",
                url=f"https://example.com/photo{i}.png",
                is_cover=i == 0,
                sort_order=i,
            )
        )
    assert post_image(client, repo.auction.id).status_code == 409
    assert not storage.uploads


def test_set_cover_changes_exactly_one_image(api):
    client, repo, _, *_ = api
    first = add_image(client, repo.auction.id)
    second = add_image(client, repo.auction.id)
    response = client.patch(
        f"/api/v1/auctions/{repo.auction.id}/images/cover",
        json={"public_id": second["public_id"]},
    )
    assert response.status_code == 200, response.text
    images = response.json()["images"]
    assert sum(img["is_cover"] for img in images) == 1
    assert images[1]["is_cover"] is True
    assert images[0]["is_cover"] is False
    assert first["public_id"] != second["public_id"]


def test_reorder_keeps_cover_and_updates_order(api):
    client, repo, _, *_ = api
    first = add_image(client, repo.auction.id)
    second = add_image(client, repo.auction.id)
    path = f"/api/v1/auctions/{repo.auction.id}/images/order"
    response = client.patch(path, json={"public_ids": [second["public_id"], first["public_id"]]})
    assert response.status_code == 200, response.text
    imgs = response.json()["images"]
    assert [x["public_id"] for x in imgs] == [second["public_id"], first["public_id"]]
    assert [x["sort_order"] for x in imgs] == [0, 1]
    assert imgs[1]["is_cover"] is True


@pytest.mark.parametrize("ids", [["other"], ["same", "same"], []])
def test_reorder_invalid_ids(api, ids):
    client, repo, _, *_ = api
    add_image(client, repo.auction.id)
    response = client.patch(
        f"/api/v1/auctions/{repo.auction.id}/images/order",
        json={"public_ids": ids},
    )
    assert response.status_code == 422


def test_delete_cover_promotes_first_remaining(api):
    client, repo, storage, *_ = api
    first = add_image(client, repo.auction.id)
    second = add_image(client, repo.auction.id)
    response = client.delete(
        f"/api/v1/auctions/{repo.auction.id}/images",
        params={"public_id": first["public_id"]},
    )
    assert response.status_code == 200, response.text
    remaining = response.json()["images"]
    assert len(remaining) == 1
    assert remaining[0]["public_id"] == second["public_id"]
    assert remaining[0]["is_cover"] is True
    assert remaining[0]["sort_order"] == 0
    assert storage.deleted == [first["public_id"]]


def test_delete_unknown_image_returns_404(api):
    client, repo, storage, *_ = api
    response = client.delete(
        f"/api/v1/auctions/{repo.auction.id}/images",
        params={"public_id": "other"},
    )
    assert response.status_code == 404
    assert storage.deleted == []


def test_set_cover_unknown_image_returns_404(api):
    client, repo, *_ = api
    response = client.patch(
        f"/api/v1/auctions/{repo.auction.id}/images/cover",
        json={"public_id": "other"},
    )
    assert response.status_code == 404


def test_unauthenticated_upload_returns_401(api):
    from app.api.dependencies import get_user_repository

    client, repo, storage, *_ = api
    app.dependency_overrides.pop(get_current_user)
    app.dependency_overrides[get_user_repository] = lambda: object()
    try:
        assert post_image(client, repo.auction.id).status_code == 401
        assert storage.uploads == []
    finally:
        app.dependency_overrides.pop(get_user_repository, None)


def test_failed_cloudinary_upload_returns_502(api):
    from app.core.image_storage import ImageStorageError

    client, repo, storage, *_ = api

    async def fail_upload(*, auction_id, contents, extension):
        raise ImageStorageError("Cloudinary unavailable")

    storage.upload_image = fail_upload
    response = post_image(client, repo.auction.id)
    assert response.status_code == 502
    assert repo.auction.images == []


def test_remote_delete_failure_keeps_database_consistent(api):
    from app.core.image_storage import ImageStorageError

    client, repo, storage, *_ = api
    uploaded = add_image(client, repo.auction.id)

    async def fail_delete(*, public_id):
        raise ImageStorageError("Cloudinary unavailable")

    storage.delete_image = fail_delete
    response = client.delete(
        f"/api/v1/auctions/{repo.auction.id}/images",
        params={"public_id": uploaded["public_id"]},
    )
    assert response.status_code == 200
    assert response.json()["images"] == []
