"""Mongo conditional write invariants and stable pagination."""


from unittest.mock import AsyncMock, MagicMock

import pytest
from pymongo import ReturnDocument

from app.models.common import utc_now
from app.repositories.admin_repository import AdminRepository


@pytest.fixture
def repository():
    db = {}
    for collection_name in ("users", "auctions", "bids", "admin_audit_logs"):
        db[collection_name] = MagicMock()
        db[collection_name].find_one = AsyncMock(return_value=None)
        db[collection_name].find_one_and_update = AsyncMock(return_value=None)
        db[collection_name].insert_one = AsyncMock()
        db[collection_name].count_documents = AsyncMock(return_value=0)
    return AdminRepository(db), db


@pytest.mark.asyncio
async def test_block_is_atomic_and_increments_token_version(repository):
    repo, db = repository
    assert await repo.update_user_active("u1", True, False) is None
    query, update = db["users"].find_one_and_update.await_args.args
    assert query == {"_id": "u1", "role": "user", "is_active": True}
    assert update["$set"]["is_active"] is False
    assert update["$inc"] == {"token_version": 1}
    assert db["users"].find_one_and_update.await_args.kwargs["return_document"] == ReturnDocument.AFTER


@pytest.mark.asyncio
async def test_cancel_requires_no_bid_count_and_no_leader(repository):
    repo, db = repository
    now = utc_now()
    await repo.cancel_no_bid_auction("a1", "active", 300, now)
    query, update = db["auctions"].find_one_and_update.await_args.args
    assert query["status"] == "active"
    assert query["leader_id"] is None
    assert query["current_price"] == 300
    assert query["bid_count"] == {"$in": [0, None]}
    assert query["ends_at"] == {"$gt": now}
    assert update["$set"]["status"] == "cancelled"
    assert db["auctions"].find_one_and_update.await_args.kwargs["return_document"] == ReturnDocument.AFTER


@pytest.mark.asyncio
async def test_draft_cancel_no_end_time_restriction(repository):
    repo, db = repository
    await repo.cancel_no_bid_auction("a1", "draft", 300, utc_now())
    query = db["auctions"].find_one_and_update.await_args.args[0]
    assert "ends_at" not in query


@pytest.mark.asyncio
async def test_repository_reads_bid_history_before_admin_cancellation(repository):
    repo, db = repository
    assert await repo.has_bids("a1") is False
    db["bids"].find_one.assert_awaited_once_with({"auction_id": "a1"}, {"_id": 1})


@pytest.mark.asyncio
async def test_users_page_applies_stable_sort_and_limits(repository):
    repo, db = repository
    cursor = MagicMock()
    cursor.sort.return_value = cursor
    cursor.skip.return_value = cursor
    cursor.limit.return_value = cursor
    cursor.to_list = AsyncMock(return_value=[])
    db["users"].find.return_value = cursor
    assert await repo.list_users({"role": "user"}, 20, 10) == []
    cursor.sort.assert_called_once_with([("created_at", -1), ("_id", 1)])
    cursor.skip.assert_called_once_with(20)
    cursor.limit.assert_called_once_with(10)
