from typing import Annotated

from fastapi import Depends
from pymongo.asynchronous.database import AsyncDatabase

from app.db.mongodb import get_database
from app.repositories.user_repository import UserRepository


def get_user_repository(
    db: Annotated[AsyncDatabase, Depends(get_database)]
) -> UserRepository:
    return UserRepository(db)
