from fastapi import FastAPI, Request
from pymongo import ASCENDING, DESCENDING, AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from app.core.config import settings


async def create_indexes(db: AsyncDatabase) -> None:
    await db["users"].create_index("email", unique=True, name="ux_users_email")
    await db["users"].create_index("username", unique=True, name="ux_users_username")

    await db["auctions"].create_index(
        [("status", ASCENDING), ("ends_at", ASCENDING)],
        name="ix_auctions_status_ends_at",
    )
    await db["auctions"].create_index(
        [("category", ASCENDING), ("status", ASCENDING)],
        name="ix_auctions_category_status",
    )
    await db["auctions"].create_index(
        [("seller_id", ASCENDING), ("created_at", DESCENDING)],
        name="ix_auctions_seller_created",
    )

    await db["bids"].create_index(
        [("auction_id", ASCENDING), ("created_at", DESCENDING)],
        name="ix_bids_auction_created",
    )
    await db["bids"].create_index(
        [("bidder_id", ASCENDING), ("created_at", DESCENDING)],
        name="ix_bids_bidder_created",
    )
    # Забезпечує унікальну послідовність ставок всередині аукціону.
    await db["bids"].create_index(
        [("auction_id", ASCENDING), ("sequence", ASCENDING)],
        unique=True,
        name="ux_bids_auction_sequence",
        partialFilterExpression={"sequence": {"$exists": True}},
    )
    # Один і той самий request_id може бути прийнятий лише раз для учасника/лота.
    await db["bids"].create_index(
        [
            ("auction_id", ASCENDING),
            ("bidder_id", ASCENDING),
            ("request_id", ASCENDING),
        ],
        unique=True,
        name="ux_bids_idempotency",
        partialFilterExpression={"request_id": {"$exists": True}},
    )

    await db["admin_audit_logs"].create_index(
        [("created_at", DESCENDING), ("_id", ASCENDING)],
        name="ix_admin_audit_created",
    )
    await db["admin_audit_logs"].create_index(
        [("action", ASCENDING), ("created_at", DESCENDING)],
        name="ix_admin_audit_action_created",
    )


async def initialize_mongodb(app: FastAPI) -> AsyncMongoClient:
    client = AsyncMongoClient(
        settings.mongodb_uri.get_secret_value(),
        serverSelectionTimeoutMS=8000,
        tz_aware=True,
    )
    try:
        await client.admin.command("ping")
        db = client[settings.mongodb_db_name]
        await create_indexes(db)
        app.state.db = db
        # get_mongo_client з app.api.dependencies повинен бачити той самий клієнт.
        app.state.mongo_client = client
        return client
    except Exception:
        await client.close()
        raise


def get_database(request: Request) -> AsyncDatabase:
    return request.app.state.db
