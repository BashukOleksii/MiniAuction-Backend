"""One-time bootstrap of the first admin; execute in a trusted terminal only.

Usage: python -m scripts.bootstrap_admin
Does not add any HTTP endpoint or print the password.
"""

import asyncio
import getpass

from pydantic import ValidationError
from pymongo import AsyncMongoClient
from pymongo.errors import DuplicateKeyError

from app.core.config import settings
from app.core.security import hash_password
from app.models.user import User


async def main() -> None:
    client = AsyncMongoClient(
        settings.mongodb_uri.get_secret_value(), serverSelectionTimeoutMS=8000
    )
    try:
        await client.admin.command("ping")
        collection = client[settings.mongodb_db_name]["users"]
        if await collection.count_documents({"role": "admin"}) != 0:
            raise SystemExit("An administrator already exists; bootstrap is disabled")
        username = input("New administrator username: ").strip()
        email = input("New administrator email: ").strip().lower()
        password = getpass.getpass("New administrator password: ")
        confirmation = getpass.getpass("Confirm password: ")
        if password != confirmation:
            raise SystemExit("Passwords do not match")
        if not 12 <= len(password) <= 128:
            raise SystemExit("Use a password between 12 and 128 characters")
        try:
            user = User(
                username=username,
                email=email,
                password_hash=hash_password(password),
                role="admin",
                is_active=True,
            )
        except ValidationError as exc:
            raise SystemExit(f"Invalid administrator data: {exc}") from exc
        try:
            await collection.insert_one(user.model_dump(by_alias=True, mode="python"))
        except DuplicateKeyError as exc:
            raise SystemExit("Username or email is already in use") from exc
        print("Initial administrator created. Keep credentials private.")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
