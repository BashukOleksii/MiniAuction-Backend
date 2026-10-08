"""Unit tests for queries, without a real MongoDB server."""
from unittest.mock import AsyncMock

import pytest
from pymongo import ReturnDocument

from app.models.user import User
from app.repositories.user_repository import UserRepository


class FakeDb(dict):
    pass


@pytest.fixture
def fake_collection():
    class Collection:
        find_one = AsyncMock()
        insert_one = AsyncMock()
        find_one_and_update = AsyncMock()

    return Collection()


@pytest.mark.asyncio
async def test_find_user_by_id(fake_collection):
    user = User(username="TestUser", email="test@example.com", password_hash="hash")
    fake_collection.find_one.return_value = user.model_dump(
        by_alias=True, mode="python"
    )
    repo = UserRepository(FakeDb(users=fake_collection))
    found = await repo.get_by_id(user.id)
    assert found is not None and found.id == user.id
    fake_collection.find_one.assert_awaited_with({"_id": user.id})


@pytest.mark.asyncio
async def test_create_user_persists_id_as_mongo_id(fake_collection):
    repo = UserRepository(FakeDb(users=fake_collection))
    user = User(username="TestUser", email="test@example.com", password_hash="hash")
    await repo.create(user)
    document = fake_collection.insert_one.await_args.args[0]
    assert document["_id"] == user.id
    assert "id" not in document
    assert document["password_hash"] == "hash"


@pytest.mark.asyncio
async def test_password_change_is_atomic_and_increments_version(fake_collection):
    repo = UserRepository(FakeDb(users=fake_collection))
    fake_collection.find_one_and_update.return_value = None
    result = await repo.update_password("id1", "oldhash", "newhash")
    assert result is None
    args, kwargs = fake_collection.find_one_and_update.await_args
    assert args[0] == {
        "_id": "id1", "password_hash": "oldhash", "is_active": True,
    }
    assert args[1]["$set"]["password_hash"] == "newhash"
    assert args[1]["$inc"] == {"token_version": 1}
    assert kwargs["return_document"] == ReturnDocument.AFTER
