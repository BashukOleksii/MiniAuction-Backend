from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.main import app
from app.models.auction import Auction
from app.models.bid import Bid
from app.models.common import utc_now
from app.repositories.auction_repository import AuctionRepository
from app.services.auction_finalization_service import AuctionFinalizationService


@pytest.mark.parametrize(
    "path,method",
    [
        ("/api/v1/admin/users", "get"),
        ("/api/v1/admin/statistics", "get"),
        ("/api/v1/auctions/{auction_id}/bids", "post"),
        ("/api/v1/auctions/{auction_id}/state", "get"),
        ("/api/v1/auctions/{auction_id}/bids/recent", "get"),
        ("/api/v1/auctions/{auction_id}/result", "get"),
    ],
)
def test_merged_routes_in_openapi(path, method):
    assert method in app.openapi()["paths"].get(path, {})


def test_bid_model_keeps_idempotency_and_sequence():
    bid = Bid(
        auction_id="auction-1",
        bidder_id="user-1",
        amount=150,
        sequence=1,
        request_id=str(uuid4()),
    )
    doc = bid.model_dump(by_alias=True)
    assert doc["sequence"] == 1
    assert doc["request_id"] == bid.request_id
    assert doc["_id"] == bid.id
    with pytest.raises(ValidationError):
        Bid(auction_id="a", bidder_id="u", amount=100, sequence=0, request_id="r")


def test_auction_model_preserves_bid_count():
    auction = Auction(
        seller_id="seller",
        title="Laptop",
        category="electronics",
        starting_price=100,
        current_price=150,
        bid_count=1,
        ends_at=utc_now() + timedelta(days=1),
    )
    assert auction.bid_count == 1
    assert auction.model_dump(by_alias=True)["bid_count"] == 1


@pytest.mark.asyncio
async def test_seller_cancel_requires_zero_bid_count():
    collection = MagicMock()
    collection.find_one_and_update = AsyncMock(return_value=None)
    repo = AuctionRepository({"auctions": collection})
    await repo.cancel("a1", "seller", "active", 100, utc_now())
    query = collection.find_one_and_update.await_args.args[0]
    assert query["bid_count"] == {"$in": [0, None]}


@pytest.mark.asyncio
async def test_private_draft_result_is_not_available():
    auction = Auction(
        seller_id="seller",
        title="Laptop",
        category="electronics",
        starting_price=100,
        current_price=100,
        ends_at=utc_now() + timedelta(days=1),
        status="draft",
    )
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=auction)
    service = AuctionFinalizationService(repo, MagicMock())
    with pytest.raises(HTTPException) as err:
        await service.get_auction_result(auction.id)
    assert err.value.status_code == 404

