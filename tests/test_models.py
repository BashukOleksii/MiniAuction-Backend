from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.models.auction import Auction, AuctionStatus


def sample_auction(**overrides) -> Auction:
    data = {
        "seller_id": "seller-123",
        "title": "Mechanical Keyboard",
        "category": "Electronics",
        "starting_price": 50,
        "current_price": 50,
        "min_bid_step": 5,
        "ends_at": datetime.now(timezone.utc) + timedelta(days=1),
        "status": AuctionStatus.ACTIVE,
    }
    data.update(overrides)
    return Auction(**data)


def test_auction_can_be_created():
    auction = sample_auction()
    document = auction.model_dump(by_alias=True, mode="python")
    assert "_id" in document
    assert document["starting_price"] == 50
    assert isinstance(document["ends_at"], datetime)


def test_current_price_cannot_be_below_starting_price():
    with pytest.raises(ValidationError):
        sample_auction(current_price=49)


def test_auction_cannot_end_before_it_starts():
    with pytest.raises(ValidationError):
        sample_auction(ends_at=datetime.now(timezone.utc) - timedelta(days=1))
