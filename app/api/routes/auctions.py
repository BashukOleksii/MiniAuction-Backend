from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pymongo import ASCENDING
from pymongo.asynchronous.database import AsyncDatabase

from app.db.mongodb import get_database
from app.models.auction import Auction, AuctionStatus


router = APIRouter()


@router.get("", response_model=list[Auction])
async def list_active_auctions(
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncDatabase = Depends(get_database),
):
    now = datetime.now(timezone.utc)
    cursor = (
        db["auctions"]
        .find({
            "status": AuctionStatus.ACTIVE.value,
            "starts_at": {"$lte": now},
            "ends_at": {"$gt": now},
        })
        .sort("ends_at", ASCENDING)
        .limit(limit)
    )
    documents = await cursor.to_list(length=limit)
    return [Auction.model_validate(document) for document in documents]
