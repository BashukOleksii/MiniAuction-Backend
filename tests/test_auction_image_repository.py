"""Query invariants for atomic image updates."""

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from pymongo import ReturnDocument

from app.models.auction import Auction, AuctionImage
from app.models.common import utc_now
from app.repositories.auction_image_repository import AuctionImageRepository


@pytest.mark.asyncio
async def test_replace_images_checks_owner_draft_and_old_image_snapshot():
    collection = type("Collection", (), {})()
    collection.find_one_and_update = AsyncMock(return_value=None)
    repo = AuctionImageRepository({"auctions": collection})
    image = AuctionImage(
        public_id="auction/one",
        url="https://res.cloudinary.com/demo/one.png",
        is_cover=True,
    )
    response = await repo.replace_draft_images(
        auction_id="a1", seller_id="seller", expected_images=[image], new_images=[]
    )
    assert response is None
    query, mutation = collection.find_one_and_update.await_args.args
    assert query == {
        "_id": "a1",
        "seller_id": "seller",
        "status": "draft",
        "images": [image.model_dump(mode="python")],
    }
    assert mutation["$set"]["images"] == []
    assert kwargs_is_after(collection)


def kwargs_is_after(collection):
    return collection.find_one_and_update.await_args.kwargs["return_document"] == ReturnDocument.AFTER


@pytest.mark.asyncio
async def test_empty_snapshot_accepts_legacy_missing_images():
    collection = type("Collection", (), {})()
    collection.find_one_and_update = AsyncMock(return_value=None)
    repo = AuctionImageRepository({"auctions": collection})
    await repo.replace_draft_images(
        auction_id="a1", seller_id="seller", expected_images=[], new_images=[]
    )
    query = collection.find_one_and_update.await_args.args[0]
    assert query["$or"] == [{"images": []}, {"images": {"$exists": False}}]


@pytest.mark.asyncio
async def test_repository_returns_full_validated_auction():
    auction = Auction(
        seller_id="seller", title="Auction", category="electronics",
        starting_price=5, current_price=5,
        ends_at=utc_now() + timedelta(days=1),
    )
    collection = type("Collection", (), {})()
    collection.find_one_and_update = AsyncMock(
        return_value=auction.model_dump(by_alias=True, mode="python")
    )
    repo = AuctionImageRepository({"auctions": collection})
    response = await repo.replace_draft_images(
        auction_id=auction.id, seller_id="seller", expected_images=[], new_images=[]
    )
    assert response is not None and response.id == auction.id
