from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from jwt import InvalidTokenError
from pwdlib import PasswordHash

from app.core.config import settings

password_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(
    password: str,
    hashed_password: str
) -> bool:
    return password_hasher.verify(
        password,
        hashed_password
    )


def create_access_token(
    user_id: str,
    role: str
) -> str:

    if not user_id or role not in ("user", "admin"):
        raise ValueError("Invalid token subject or role")

    now = datetime.now(timezone.utc)

    payload = {
        "sub": user_id,
        "role": role,
        "iat": now,
        "exp": now + timedelta(
            minutes=settings.jwt_access_token_expire_minutes
        )
    }

    return jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm
    )


def decode_access_token(token: str) -> dict[str, Any]:

    payload = jwt.decode(
        token,
        settings.jwt_secret_key.get_secret_value(),
        algorithms=[settings.jwt_algorithm],
        options={
            "require": ["sub", "role", "iat", "exp"]
        }
    )

    if not isinstance(payload["sub"], str) or not payload["sub"]:
        raise InvalidTokenError("Invalid token subject")

    if payload["role"] not in ("user", "admin"):
        raise InvalidTokenError("Invalid token role")

    return payload
