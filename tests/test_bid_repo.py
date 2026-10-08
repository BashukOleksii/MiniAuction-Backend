import os
import uuid
from datetime import datetime, timezone
from typing import Optional

import pytest
import pytest_asyncio
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from pymongo import AsyncMongoClient
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.errors import DuplicateKeyError

load_dotenv()

class Bid(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), alias="_id")
    auction_id: str
    bidder_id: str
    amount: float
    sequence: int
    request_id: str
    created_at: Optional[datetime] = None

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
    }


class BidRepository:
    def __init__(self, db):
        self.collection = db["bids"]

    async def create_bid(
        self,
        bid: Bid,
        session: AsyncClientSession,
    ) -> Bid:
        """A1: Inserts bid under session, propagates DuplicateKeyError."""
        doc = bid.model_dump(by_alias=True)
        if not doc.get("_id"):
            doc["_id"] = str(uuid.uuid4())

        doc["created_at"] = datetime.now(timezone.utc)

        try:
            await self.collection.insert_one(doc, session=session)
        except DuplicateKeyError:
            raise

        return Bid.model_validate(doc)

    async def get_bid_by_id(
        self,
        bid_id: str,
        session: Optional[AsyncClientSession] = None,
    ) -> Optional[Bid]:
        """A2: Finds bid by string UUID."""
        doc = await self.collection.find_one({"_id": bid_id}, session=session)
        if not doc:
            return None
        return Bid.model_validate(doc)


TEST_MONGODB_URI = os.getenv("MONGODB_URI")
if not TEST_MONGODB_URI:
    TEST_MONGODB_URI = "mongodb://127.0.0.1:27017/?replicaSet=rs0&directConnection=true"

TEST_DB_NAME = "mini_auction_test_suite"


@pytest_asyncio.fixture
async def mongo_client():
    client = AsyncMongoClient(TEST_MONGODB_URI)
    yield client
    await client.close()


@pytest_asyncio.fixture
async def bid_repo(mongo_client):
    db = mongo_client[TEST_DB_NAME]
    repo = BidRepository(db)

    await repo.collection.create_index("request_id", unique=True, sparse=True)
    await repo.collection.create_index(
        [("auction_id", 1), ("sequence", 1)],
        unique=True,
    )

    yield repo

    await repo.collection.delete_many({})


@pytest.fixture
def make_bid():
    def _create(
        amount: float = 100.0,
        seq: int = 1,
        req_id: Optional[str] = None,
    ) -> Bid:
        return Bid(
            auction_id=str(uuid.uuid4()),
            bidder_id=str(uuid.uuid4()),
            amount=amount,
            sequence=seq,
            request_id=req_id or f"req-{uuid.uuid4()}",
        )
    return _create


@pytest.mark.asyncio
async def test_a1_create_bid_success_under_session(mongo_client, bid_repo, make_bid):
    bid_in = make_bid(amount=250.0, seq=1)

    async with mongo_client.start_session() as session:
        await session.start_transaction()
        saved_bid = await bid_repo.create_bid(bid_in, session=session)
        await session.commit_transaction()

    raw_doc = await bid_repo.collection.find_one({"_id": saved_bid.id})
    assert raw_doc is not None
    assert raw_doc["amount"] == 250.0
    assert raw_doc["sequence"] == 1
    assert raw_doc["created_at"] is not None
    assert isinstance(raw_doc["_id"], str)


@pytest.mark.asyncio
async def test_a1_create_bid_rollback_on_failure(mongo_client, bid_repo, make_bid):
    bid_in = make_bid(amount=500.0)

    with pytest.raises(ValueError, match="Abort simulation"):
        async with mongo_client.start_session() as session:
            await session.start_transaction()
            try:
                await bid_repo.create_bid(bid_in, session=session)
                raise ValueError("Abort simulation")
            except Exception:
                await session.abort_transaction()
                raise

    count = await bid_repo.collection.count_documents({"_id": bid_in.id})
    assert count == 0


@pytest.mark.asyncio
async def test_a1_create_bid_duplicate_key_error(mongo_client, bid_repo, make_bid):
    common_request_id = f"fixed-req-{uuid.uuid4()}"
    bid_first = make_bid(amount=100.0, req_id=common_request_id)
    bid_duplicate = make_bid(amount=200.0, req_id=common_request_id)

    async with mongo_client.start_session() as session:
        await session.start_transaction()
        await bid_repo.create_bid(bid_first, session=session)
        await session.commit_transaction()

    with pytest.raises(DuplicateKeyError):
        async with mongo_client.start_session() as session:
            await session.start_transaction()
            try:
                await bid_repo.create_bid(bid_duplicate, session=session)
                await session.commit_transaction()
            except Exception:
                await session.abort_transaction()
                raise


@pytest.mark.asyncio
async def test_a2_get_bid_by_id_existing(mongo_client, bid_repo, make_bid):
    bid_in = make_bid(amount=777.0)

    async with mongo_client.start_session() as session:
        await session.start_transaction()
        created = await bid_repo.create_bid(bid_in, session=session)
        await session.commit_transaction()

    found = await bid_repo.get_bid_by_id(created.id)

    assert found is not None
    assert isinstance(found, Bid)
    assert found.id == created.id
    assert found.amount == 777.0


@pytest.mark.asyncio
async def test_a2_get_bid_by_id_not_found(bid_repo):
    random_uuid = str(uuid.uuid4())
    result = await bid_repo.get_bid_by_id(random_uuid)
    assert result is None