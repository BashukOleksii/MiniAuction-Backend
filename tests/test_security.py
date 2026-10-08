
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from jwt import ExpiredSignatureError, InvalidTokenError

from app.core.config import settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_hash_password():
    password = "MyStrongPassword123!"

    hashed = hash_password(password)

    assert hashed != password
    assert verify_password(password, hashed)


def test_wrong_password():
    hashed = hash_password("CorrectPassword123!")

    assert not verify_password(
        "WrongPassword123!",
        hashed
    )


def test_create_and_decode_token():
    token = create_access_token(
        user_id="test-user-id",
        role="user"
    )

    payload = decode_access_token(token)

    assert payload["sub"] == "test-user-id"
    assert payload["role"] == "user"
    assert "exp" in payload


def test_invalid_token():
    with pytest.raises(InvalidTokenError):
        decode_access_token("invalid.token.value")


def test_expired_token():
    now = datetime.now(timezone.utc)

    payload = {
        "sub": "test-user-id",
        "role": "user",
        "iat": now - timedelta(hours=1),
        "exp": now - timedelta(minutes=1)
    }

    token = jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm
    )

    with pytest.raises(ExpiredSignatureError):
        decode_access_token(token)


def test_invalid_token_role():
    with pytest.raises(ValueError):
        create_access_token(
            user_id="test-user-id",
            role="superadmin"
        )
