"""Pure tests of MongoDB query construction and lifecycle state."""

from datetime import timedelta

from app.models.auction import Auction
from app.models.common import utc_now
from app.services.auction_service import effective_status, public_query


def test_query_active_is_bounded_by_dates():
    now = utc_now()
    query = public_query(now, "active", None, None, None, None)
    assert query["status"] == "active"
    assert query["starts_at"] == {"$lte": now}
    assert query["ends_at"] == {"$gt": now}


def test_query_for_finished_includes_unfinalized_auctions():
    now = utc_now()
    query = public_query(now, "finished", None, None, None, None)
    assert {"status": "finished"} in query["$or"]
    assert {"status": "active", "ends_at": {"$lte": now}} in query["$or"]


def test_filter_includes_category_price_and_escaped_search():
    query = public_query(utc_now(), "scheduled", "(key).*", "Books", 10, 100)
    assert query["category"] == "books"
    assert query["current_price"] == {"$gte": 10, "$lte": 100}
    assert query["$and"][0]["$or"][0]["title"]["$regex"] == r"\(key\)\.\*"


def test_expired_published_lot_is_not_effectively_active():
    now = utc_now()
    auction = Auction(
        seller_id="seller-id",
        title="Test auction",
        category="other",
        starting_price=10,
        current_price=10,
        min_bid_step=1,
        starts_at=now - timedelta(days=2),
        ends_at=now - timedelta(days=1),
        status="active",
    )
    assert effective_status(auction, now) == "finished"
