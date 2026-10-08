"""Repository unit tests checking safe conditional MongoDB updates."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from pymongo import ReturnDocument

from app.models.common import utc_now
from app.repositories.auction_repository import AuctionRepository


@pytest.fixture
def repo():
    collection = MagicMock()
    collection.find_one = AsyncMock(return_value=None)
    collection.insert_one = AsyncMock()
    collection.find_one_and_update = AsyncMock(return_value=None)
    collection.count_documents = AsyncMock(return_value=0)
    db = {"auctions": collection}
    return AuctionRepository(db), collection


@pytest.mark.asyncio
async def test_publish_requires_draft_and_unexpired_lot(repo):
    repository, collection = repo
    now = utc_now()
    result = await repository.publish("auction-id", "seller-id", now)
    assert result is None
    query, mutation = collection.find_one_and_update.await_args.args
    assert query == {
        "_id": "auction-id",
        "seller_id": "seller-id",
        "status": "draft",
        "ends_at": {"$gt": now},
    }
    assert mutation["$set"]["status"] == "active"
    assert collection.find_one_and_update.await_args.kwargs["return_document"] == ReturnDocument.AFTER


@pytest.mark.asyncio
async def test_update_cannot_modify_non_draft(repo):
    repository, collection = repo
    await repository.update_draft("auction-id", "seller-id", {"title": "New title"})
    query, mutation = collection.find_one_and_update.await_args.args
    assert query["status"] == "draft"
    assert query["seller_id"] == "seller-id"
    assert mutation["$set"]["title"] == "New title"


@pytest.mark.asyncio
async def test_cancel_protects_against_concurrent_bid(repo):
    repository, collection = repo
    now = utc_now()
    await repository.cancel("auction-id", "seller-id", "active", 100, now)
    query, mutation = collection.find_one_and_update.await_args.args
    assert query["leader_id"] is None
    assert query["current_price"] == 100
    assert query["status"] == "active"
    assert query["ends_at"] == {"$gt": now}
    assert mutation["$set"]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_draft_does_not_need_future_deadline(repo):
    repository, collection = repo
    await repository.cancel("auction-id", "seller-id", "draft", 100, utc_now())
    query = collection.find_one_and_update.await_args.args[0]
    assert "ends_at" not in query


@pytest.mark.asyncio
async def test_catalog_pagination_is_applied_in_mongo(repo):
    repository, collection = repo
    cursor = MagicMock()
    cursor.sort.return_value = cursor
    cursor.skip.return_value = cursor
    cursor.limit.return_value = cursor
    cursor.to_list = AsyncMock(return_value=[])
    collection.find.return_value = cursor
    results = await repository.find_public(
        {"status": "active"}, "current_price", -1, 20, 10
    )
    assert results == []
    collection.find.assert_called_once_with({"status": "active"})
    cursor.sort.assert_called_once_with([("current_price", -1), ("_id", 1)])
    cursor.skip.assert_called_once_with(20)
    cursor.limit.assert_called_once_with(10)
    cursor.to_list.assert_awaited_once_with(length=10)
