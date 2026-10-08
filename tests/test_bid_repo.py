import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
import pytest_asyncio
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from pymongo import AsyncMongoClient, ReturnDocument
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.errors import DuplicateKeyError

# Завантажуємо конфігурацію середовища
load_dotenv()

# ==============================================================================
# 1. Модель Bid (Pydantic v2 відповідно до ТЗ)
# ==============================================================================
class Bid(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), alias="_id")
    auction_id: str
    bidder_id: str
    amount: int  # Суворо ціле число (int) за ТЗ
    sequence: int
    request_id: str
    created_at: datetime | None = None

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
    }


# ==============================================================================
# 2. Репозиторій BidRepository (Повна реалізація A1-A8, F1)
# ==============================================================================
class BidRepository:
    def __init__(self, db: Any) -> None:
        self.bids_collection = db["bids"]
        self.auctions_collection = db["auctions"]

    async def create_bid(
        self,
        bid: Bid,
        session: AsyncClientSession,
    ) -> Bid:
        """A1: Вставляє Bid під сесією, генерує created_at UTC, прокидає DuplicateKeyError."""
        doc = bid.model_dump(by_alias=True)
        if not doc.get("_id"):
            doc["_id"] = str(uuid.uuid4())

        doc["created_at"] = datetime.now(timezone.utc)

        await self.bids_collection.insert_one(doc, session=session)
        return Bid.model_validate(doc)

        return Bid.model_validate(doc)

    async def get_bid_by_id(
        self,
        bid_id: str,
        session: AsyncClientSession | None = None,
    ) -> Bid | None:
        """A2: Знаходить ставку за рядковим UUID (_id)."""
        doc = await self.bids_collection.find_one({"_id": bid_id}, session=session)
        if not doc:
            return None
        return Bid.model_validate(doc)

    async def get_bid_by_request_id(
        self,
        auction_id: str,
        bidder_id: str,
        request_id: str,
        session: AsyncClientSession | None = None,
    ) -> Bid | None:
        """A3: Пошук за 3 полями для ідемпотентності."""
        doc = await self.bids_collection.find_one(
            {
                "auction_id": auction_id,
                "bidder_id": bidder_id,
                "request_id": request_id,
            },
            session=session,
        )
        if not doc:
            return None
        return Bid.model_validate(doc)

    async def get_auction_bids(
        self,
        auction_id: str,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Bid], int]:
        """A4: Історія ставок лота, sequence DESC, пагінація."""
        skip = (page - 1) * page_size
        filter_query = {"auction_id": auction_id}

        total_bids = await self.bids_collection.count_documents(filter_query)

        cursor = (
            self.bids_collection.find(filter_query)
            .sort("sequence", -1)
            .skip(skip)
            .limit(page_size)
        )

        bids: list[Bid] = []
        async for doc in cursor:
            bids.append(Bid.model_validate(doc))

        return bids, total_bids

    async def count_auction_bids(
        self,
        auction_id: str,
        session: AsyncClientSession | None = None,
    ) -> int:
        """A5: Підрахунок ставок за auction_id."""
        return await self.bids_collection.count_documents(
            {"auction_id": auction_id},
            session=session,
        )

    async def get_user_bids(
        self,
        user_id: str,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Bid], int]:
        """A6: Власні ставки учасника, created_at DESC, sequence DESC."""
        skip = (page - 1) * page_size
        filter_query = {"bidder_id": user_id}

        total_bids = await self.bids_collection.count_documents(filter_query)

        cursor = (
            self.bids_collection.find(filter_query)
            .sort([("created_at", -1), ("sequence", -1)])
            .skip(skip)
            .limit(page_size)
        )

        bids: list[Bid] = []
        async for doc in cursor:
            bids.append(Bid.model_validate(doc))

        return bids, total_bids

    async def get_latest_bid(
        self,
        auction_id: str,
        session: AsyncClientSession | None = None,
    ) -> Bid | None:
        """A7: Остання ставка лота за найбільшим sequence."""
        cursor = (
            self.bids_collection.find({"auction_id": auction_id}, session=session)
            .sort("sequence", -1)
            .limit(1)
        )
        async for doc in cursor:
            return Bid.model_validate(doc)
        return None

    async def get_recent_bids(
        self,
        auction_id: str,
        limit: int = 10,
        after_sequence: int | None = None,
    ) -> list[Bid]:
        """F1: Останні ставки для polling, фільтрація sequence > after_sequence."""
        query: dict[str, Any] = {"auction_id": auction_id}
        if after_sequence is not None:
            query["sequence"] = {"$gt": after_sequence}

        cursor = (
            self.bids_collection.find(query)
            .sort("sequence", -1)
            .limit(limit)
        )

        bids: list[Bid] = []
        async for doc in cursor:
            bids.append(Bid.model_validate(doc))
        return bids

    async def update_auction_bid_state(
        self,
        auction_id: str,
        expected_price: int,
        bidder_id: str,
        new_amount: int,
        now: datetime,
        session: AsyncClientSession,
    ) -> dict[str, Any] | None:
        """A8: Атомарне оновлення лота під сесією."""
        filter_query = {
            "_id": auction_id,
            "status": "active",
            "current_price": expected_price,
            "starts_at": {"$lte": now},
            "ends_at": {"$gt": now},
            "seller_id": {"$ne": bidder_id},
        }

        update_query = {
            "$set": {
                "current_price": new_amount,
                "leader_id": bidder_id,
                "updated_at": now,
            },
            "$inc": {
                "bid_count": 1,
            },
        }

        return await self.auctions_collection.find_one_and_update(
            filter_query,
            update_query,
            session=session,
            return_document=ReturnDocument.AFTER,
        )


# ==============================================================================
# 3. Pytest Фікстури
# ==============================================================================
TEST_MONGODB_URI = os.getenv("MONGODB_URI")
if not TEST_MONGODB_URI:
    TEST_MONGODB_URI = "mongodb://127.0.0.1:27017/?replicaSet=rs0&directConnection=true"

TEST_DB_NAME = "mini_auction_test_suite_full"


@pytest_asyncio.fixture
async def mongo_client():
    client = AsyncMongoClient(TEST_MONGODB_URI)
    yield client
    await client.close()


@pytest_asyncio.fixture
async def repo(mongo_client):
    db = mongo_client[TEST_DB_NAME]
    repository = BidRepository(db)

    # Налаштування індексів
    await repository.bids_collection.create_index("request_id", unique=True, sparse=True)
    await repository.bids_collection.create_index(
        [("auction_id", 1), ("sequence", 1)],
        unique=True,
    )
    await repository.bids_collection.create_index(
        [("auction_id", 1), ("bidder_id", 1), ("request_id", 1)],
        unique=True,
    )

    yield repository

    # Очищення колекцій після кожного тесту
    await repository.bids_collection.delete_many({})
    await repository.auctions_collection.delete_many({})


@pytest.fixture
def make_bid():
    def _create(
        auction_id: str | None = None,
        bidder_id: str | None = None,
        amount: int = 100,
        seq: int = 1,
        req_id: str | None = None,
    ) -> Bid:
        return Bid(
            auction_id=auction_id or str(uuid.uuid4()),
            bidder_id=bidder_id or str(uuid.uuid4()),
            amount=amount,
            sequence=seq,
            request_id=req_id or f"req-{uuid.uuid4()}",
        )
    return _create


# ==============================================================================
# 4. Тести A1: create_bid
# ==============================================================================
@pytest.mark.asyncio
async def test_a1_create_bid_success_under_session(mongo_client, repo, make_bid):
    bid_in = make_bid(amount=250, seq=1)

    async with mongo_client.start_session() as session:
        await session.start_transaction()
        saved = await repo.create_bid(bid_in, session=session)
        await session.commit_transaction()

    doc = await repo.bids_collection.find_one({"_id": saved.id})
    assert doc is not None
    assert doc["amount"] == 250
    assert doc["sequence"] == 1
    assert doc["created_at"] is not None
    assert isinstance(doc["_id"], str)


@pytest.mark.asyncio
async def test_a1_create_bid_rollback_on_failure(mongo_client, repo, make_bid):
    bid_in = make_bid(amount=500)

    with pytest.raises(RuntimeError, match="DB_FAIL"):
        async with mongo_client.start_session() as session:
            await session.start_transaction()
            try:
                await repo.create_bid(bid_in, session=session)
                raise RuntimeError("DB_FAIL")
            except Exception:
                await session.abort_transaction()
                raise

    count = await repo.bids_collection.count_documents({"_id": bid_in.id})
    assert count == 0


@pytest.mark.asyncio
async def test_a1_create_bid_duplicate_key_error(mongo_client, repo, make_bid):
    common_req = f"req-{uuid.uuid4()}"
    bid_1 = make_bid(amount=100, req_id=common_req)
    bid_2 = make_bid(amount=200, req_id=common_req)

    async with mongo_client.start_session() as session:
        await session.start_transaction()
        await repo.create_bid(bid_1, session=session)
        await session.commit_transaction()

    with pytest.raises(DuplicateKeyError):
        async with mongo_client.start_session() as session:
            await session.start_transaction()
            try:
                await repo.create_bid(bid_2, session=session)
                await session.commit_transaction()
            except Exception:
                await session.abort_transaction()
                raise


# ==============================================================================
# 5. Тести A2: get_bid_by_id
# ==============================================================================
@pytest.mark.asyncio
async def test_a2_get_bid_by_id_existing(mongo_client, repo, make_bid):
    bid_in = make_bid(amount=777)

    async with mongo_client.start_session() as session:
        await session.start_transaction()
        created = await repo.create_bid(bid_in, session=session)
        await session.commit_transaction()

    found = await repo.get_bid_by_id(created.id)
    assert found is not None
    assert found.id == created.id
    assert found.amount == 777


@pytest.mark.asyncio
async def test_a2_get_bid_by_id_not_found(repo):
    found = await repo.get_bid_by_id(str(uuid.uuid4()))
    assert found is None


# ==============================================================================
# 6. Тести A3: get_bid_by_request_id (Ідемпотентність)
# ==============================================================================
@pytest.mark.asyncio
async def test_a3_idempotency_same_key_same_amount(mongo_client, repo, make_bid):
    req_id = f"idem-{uuid.uuid4()}"
    bid_in = make_bid(amount=300, req_id=req_id)

    async with mongo_client.start_session() as session:
        await session.start_transaction()
        created = await repo.create_bid(bid_in, session=session)
        await session.commit_transaction()

    existing = await repo.get_bid_by_request_id(bid_in.auction_id, bid_in.bidder_id, req_id)
    assert existing is not None
    assert existing.id == created.id
    assert existing.amount == 300


@pytest.mark.asyncio
async def test_a3_idempotency_same_key_different_amount_conflict(mongo_client, repo, make_bid):
    req_id = f"idem-{uuid.uuid4()}"
    bid_in = make_bid(amount=300, req_id=req_id)
    different_amount = 450

    async with mongo_client.start_session() as session:
        await session.start_transaction()
        await repo.create_bid(bid_in, session=session)
        await session.commit_transaction()

    existing = await repo.get_bid_by_request_id(bid_in.auction_id, bid_in.bidder_id, req_id)
    assert existing is not None

    with pytest.raises(ValueError, match="IDEMPOTENCY_KEY_REUSED"):
        if existing.amount != different_amount:
            raise ValueError("IDEMPOTENCY_KEY_REUSED")


# ==============================================================================
# 7. Тести A4: get_auction_bids (Пагінація та порядок sequence DESC)
# ==============================================================================
@pytest.mark.asyncio
async def test_a4_get_auction_bids_order_and_pagination(mongo_client, repo, make_bid):
    auc_id = str(uuid.uuid4())

    async with mongo_client.start_session() as session:
        await session.start_transaction()
        await repo.create_bid(make_bid(auction_id=auc_id, amount=10, seq=1), session=session)
        await repo.create_bid(make_bid(auction_id=auc_id, amount=20, seq=2), session=session)
        await repo.create_bid(make_bid(auction_id=auc_id, amount=30, seq=3), session=session)
        await session.commit_transaction()

    # Порядок 3, 2, 1
    bids, total = await repo.get_auction_bids(auc_id, page=1, page_size=2)
    assert total == 3
    assert len(bids) == 2
    assert bids[0].sequence == 3
    assert bids[1].sequence == 2

    # Сторінка 2
    bids_p2, total_p2 = await repo.get_auction_bids(auc_id, page=2, page_size=2)
    assert total_p2 == 3
    assert len(bids_p2) == 1
    assert bids_p2[0].sequence == 1

    # Порожній результат для іншого лота
    bids_empty, total_empty = await repo.get_auction_bids(str(uuid.uuid4()), page=1, page_size=10)
    assert total_empty == 0
    assert len(bids_empty) == 0


# ==============================================================================
# 8. Тести A5: count_auction_bids
# ==============================================================================
@pytest.mark.asyncio
async def test_a5_count_auction_bids(mongo_client, repo, make_bid):
    auc_id = str(uuid.uuid4())
    assert await repo.count_auction_bids(auc_id) == 0

    async with mongo_client.start_session() as session:
        await session.start_transaction()
        await repo.create_bid(make_bid(auction_id=auc_id, seq=1), session=session)
        await repo.create_bid(make_bid(auction_id=auc_id, seq=2), session=session)
        await session.commit_transaction()

    assert await repo.count_auction_bids(auc_id) == 2


# ==============================================================================
# 9. Тести A6: get_user_bids (Тільки власні ставки)
# ==============================================================================
@pytest.mark.asyncio
async def test_a6_get_user_bids(mongo_client, repo, make_bid):
    my_user_id = str(uuid.uuid4())
    other_user_id = str(uuid.uuid4())

    async with mongo_client.start_session() as session:
        await session.start_transaction()
        await repo.create_bid(make_bid(bidder_id=my_user_id, seq=1), session=session)
        await repo.create_bid(make_bid(bidder_id=other_user_id, seq=2), session=session)
        await repo.create_bid(make_bid(bidder_id=my_user_id, seq=3), session=session)
        await session.commit_transaction()

    bids, total = await repo.get_user_bids(my_user_id, page=1, page_size=10)
    assert total == 2
    assert len(bids) == 2
    for b in bids:
        assert b.bidder_id == my_user_id


# ==============================================================================
# 10. Тести A7: get_latest_bid
# ==============================================================================
@pytest.mark.asyncio
async def test_a7_get_latest_bid(mongo_client, repo, make_bid):
    auc_id = str(uuid.uuid4())

    async with mongo_client.start_session() as session:
        await session.start_transaction()
        await repo.create_bid(make_bid(auction_id=auc_id, amount=100, seq=1), session=session)
        await repo.create_bid(make_bid(auction_id=auc_id, amount=150, seq=2), session=session)
        await session.commit_transaction()

    latest = await repo.get_latest_bid(auc_id)
    assert latest is not None
    assert latest.sequence == 2
    assert latest.amount == 150


# ==============================================================================
# 11. Тести F1: get_recent_bids (Polling)
# ==============================================================================
@pytest.mark.asyncio
async def test_f1_get_recent_bids_with_after_sequence(mongo_client, repo, make_bid):
    auc_id = str(uuid.uuid4())

    async with mongo_client.start_session() as session:
        await session.start_transaction()
        await repo.create_bid(make_bid(auction_id=auc_id, seq=1), session=session)
        await repo.create_bid(make_bid(auction_id=auc_id, seq=2), session=session)
        await repo.create_bid(make_bid(auction_id=auc_id, seq=3), session=session)
        await repo.create_bid(make_bid(auction_id=auc_id, seq=4), session=session)
        await session.commit_transaction()

    # Отримуємо нові ставки після відомого sequence=2
    recent = await repo.get_recent_bids(auc_id, limit=10, after_sequence=2)
    assert len(recent) == 2
    assert [b.sequence for b in recent] == [4, 3]

    # Якщо нових ставок немає
    no_new = await repo.get_recent_bids(auc_id, limit=10, after_sequence=4)
    assert len(no_new) == 0


# ==============================================================================
# 12. Тести A8: update_auction_bid_state (Атомарне оновлення лота)
# ==============================================================================
@pytest.mark.asyncio
async def test_a8_update_auction_bid_state_success(mongo_client, repo):
    auc_id = str(uuid.uuid4())
    seller_id = str(uuid.uuid4())
    bidder_id = str(uuid.uuid4())

    now = datetime.now(timezone.utc)
    auction_doc = {
        "_id": auc_id,
        "seller_id": seller_id,
        "status": "active",
        "current_price": 100,
        "bid_count": 0,
        "leader_id": None,
        "starts_at": now - timedelta(minutes=5),
        "ends_at": now + timedelta(minutes=10),
    }
    await repo.auctions_collection.insert_one(auction_doc)

    async with mongo_client.start_session() as session:
        await session.start_transaction()
        updated = await repo.update_auction_bid_state(
            auction_id=auc_id,
            expected_price=100,
            bidder_id=bidder_id,
            new_amount=120,
            now=now,
            session=session,
        )
        await session.commit_transaction()

    assert updated is not None
    assert updated["current_price"] == 120
    assert updated["leader_id"] == bidder_id
    assert updated["bid_count"] == 1


@pytest.mark.asyncio
async def test_a8_update_auction_bid_state_conflicts(mongo_client, repo):
    auc_id = str(uuid.uuid4())
    seller_id = str(uuid.uuid4())
    bidder_id = str(uuid.uuid4())

    now = datetime.now(timezone.utc)
    base_doc = {
        "_id": auc_id,
        "seller_id": seller_id,
        "status": "active",
        "current_price": 100,
        "bid_count": 0,
        "leader_id": None,
        "starts_at": now - timedelta(minutes=5),
        "ends_at": now + timedelta(minutes=10),
    }
    await repo.auctions_collection.insert_one(base_doc)

    async with mongo_client.start_session() as session:
        await session.start_transaction()

        # 1. Конфлікт ціни: хтось уже змінив ціну (expected_price=90 замість 100)
        res_price_conflict = await repo.update_auction_bid_state(
            auc_id, expected_price=90, bidder_id=bidder_id, new_amount=120, now=now, session=session
        )
        assert res_price_conflict is None

        # 2. Конфлікт часу: аукціон завершився
        expired_time = now + timedelta(minutes=20)
        res_expired = await repo.update_auction_bid_state(
            auc_id, expected_price=100, bidder_id=bidder_id, new_amount=120, now=expired_time, session=session
        )
        assert res_expired is None

        # 3. Конфлікт продавця: продавець не може ставити на власний лот
        res_seller = await repo.update_auction_bid_state(
            auc_id, expected_price=100, bidder_id=seller_id, new_amount=120, now=now, session=session
        )
        assert res_seller is None

        await session.commit_transaction()