from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import PyMongoError

from app.db.mongodb import get_database

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok"}



@router.get("/health/db")
async def database_health(
    db: Annotated[AsyncDatabase, Depends(get_database)]
):
    try:
        await db.command("ping")

        return {
            "status": "ok",
            "database": "connected"
        }

    except PyMongoError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable"
        )
