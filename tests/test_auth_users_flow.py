"""HTTP tests that exercise the real routers/services without MongoDB Atlas."""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from pymongo.errors import DuplicateKeyError

from app.api.dependencies import get_user_repository
from app.main import app
from app.models.common import utc_now
from app.models.user import User


class FakeUserRepository:
    def __init__(self):
        self.users: dict[str, User] = {}
        self.duplicate_on_update = False

    async def get_by_id(self, user_id: str) -> User | None:
        return self.users.get(user_id)

    async def get_by_email(self, email: str) -> User | None:
        return next(
            (u for u in self.users.values() if str(u.email) == email.lower()), None
        )

    async def get_by_username(self, username: str) -> User | None:
        return next(
            (u for u in self.users.values() if u.username == username), None
        )

    async def create(self, user: User) -> User:
        if await self.get_by_email(str(user.email)) or await self.get_by_username(
            user.username
        ):
            raise DuplicateKeyError("duplicate key")
        self.users[user.id] = user
        return user

    async def update_profile(self, user_id: str, changes: dict) -> User | None:
        if self.duplicate_on_update:
            raise DuplicateKeyError("duplicate key")
        user = await self.get_by_id(user_id)
        if user is None or not user.is_active:
            return None
        updated = user.model_copy(update={**changes, "updated_at": utc_now()})
        self.users[user_id] = updated
        return updated

    async def update_password(
        self, user_id: str, expected_hash: str, new_password_hash: str
    ) -> User | None:
        user = await self.get_by_id(user_id)
        if user is None or not user.is_active or user.password_hash != expected_hash:
            return None
        updated = user.model_copy(
            update={
                "password_hash": new_password_hash,
                "token_version": user.token_version + 1,
                "updated_at": utc_now(),
            }
        )
        self.users[user_id] = updated
        return updated


@pytest.fixture
def api():
    repo = FakeUserRepository()
    app.dependency_overrides[get_user_repository] = lambda: repo
    client = TestClient(app)  # Без lifespan: Atlas не потрібен для цих тестів
    try:
        yield client, repo
    finally:
        client.close()
        app.dependency_overrides.clear()


def register(client: TestClient, username="Oleksii", email="user@example.com"):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": email,
            "password": "Password123!",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def login(client: TestClient, password="Password123!", email="user@example.com"):
    return client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )


def auth(token: str):
    return {"Authorization": f"Bearer {token}"}


def test_registration_then_login_then_me(api):
    client, _ = api
    user = register(client)
    response = login(client, email="USER@EXAMPLE.COM")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["token_type"] == "bearer"
    me = client.get("/api/v1/users/me", headers=auth(body["access_token"]))
    assert me.status_code == 200
    assert me.json()["id"] == user["id"]
    assert me.json()["email"] == "user@example.com"
    assert "password_hash" not in me.json()
    assert "token_version" not in me.json()


@pytest.mark.parametrize("password", ["Wrong123!", "", "not-the-password"])
def test_login_wrong_password(api, password):
    client, _ = api
    register(client)
    response = login(client, password=password)
    assert response.status_code in (401, 422)
    assert "access_token" not in response.text


def test_login_unknown_email_returns_401(api):
    client, _ = api
    response = login(client, email="unknown@example.com")
    assert response.status_code == 401


def test_me_without_bearer_returns_401(api):
    client, _ = api
    assert client.get("/api/v1/users/me").status_code == 401
    assert client.get(
        "/api/v1/users/me", headers=auth("bad.token")
    ).status_code == 401


def test_inactive_user_cannot_login_or_use_token(api):
    client, repo = api
    user = register(client)
    token = login(client).json()["access_token"]
    repo.users[user["id"]].is_active = False
    assert login(client).status_code == 401
    assert client.get("/api/v1/users/me", headers=auth(token)).status_code == 401


def test_patch_profile_and_public_view(api):
    client, _ = api
    user = register(client)
    token = login(client).json()["access_token"]
    update = client.patch(
        "/api/v1/users/me",
        headers=auth(token),
        json={"username": "NewUser", "email": "NEW@EXAMPLE.COM"},
    )
    assert update.status_code == 200, update.text
    assert update.json()["username"] == "NewUser"
    assert update.json()["email"] == "new@example.com"
    public = client.get(f"/api/v1/users/{user['id']}")
    assert public.status_code == 200
    assert public.json()["username"] == "NewUser"
    assert "email" not in public.json()
    assert "role" not in public.json()
    assert "password_hash" not in public.json()
    assert isinstance(datetime.fromisoformat(update.json()["updated_at"]), datetime)
    assert login(client, email="new@example.com").status_code == 200


def test_patch_rejects_forbidden_fields_and_empty_body(api):
    client, _ = api
    register(client)
    token = login(client).json()["access_token"]
    for payload in ({}, {"role": "admin"}, {"username": None}, {"username": "  "}):
        response = client.patch(
            "/api/v1/users/me", headers=auth(token), json=payload
        )
        assert response.status_code == 422, response.text


def test_patch_username_conflict(api):
    client, _ = api
    register(client)
    register(client, username="AnotherUser", email="other@example.com")
    token = login(client).json()["access_token"]
    response = client.patch(
        "/api/v1/users/me", headers=auth(token), json={"username": "AnotherUser"}
    )
    assert response.status_code == 409


def test_patch_race_duplicate_key_maps_to_409(api):
    client, repo = api
    register(client)
    token = login(client).json()["access_token"]
    repo.duplicate_on_update = True
    response = client.patch(
        "/api/v1/users/me", headers=auth(token), json={"username": "Available"}
    )
    assert response.status_code == 409


def test_change_password_revokes_old_token(api):
    client, _ = api
    register(client)
    old_token = login(client).json()["access_token"]
    response = client.patch(
        "/api/v1/users/me/password",
        headers=auth(old_token),
        json={
            "current_password": "Password123!",
            "new_password": "NewPassword456!",
        },
    )
    assert response.status_code == 204, response.text
    assert client.get("/api/v1/users/me", headers=auth(old_token)).status_code == 401
    assert login(client, password="Password123!").status_code == 401
    new_login = login(client, password="NewPassword456!")
    assert new_login.status_code == 200
    assert client.get(
        "/api/v1/users/me", headers=auth(new_login.json()["access_token"])
    ).status_code == 200


def test_change_password_wrong_current_and_same_password(api):
    client, _ = api
    register(client)
    token = login(client).json()["access_token"]
    wrong = client.patch(
        "/api/v1/users/me/password", headers=auth(token),
        json={"current_password": "wrong", "new_password": "SomethingNew123!"},
    )
    assert wrong.status_code == 400
    same = client.patch(
        "/api/v1/users/me/password", headers=auth(token),
        json={"current_password": "Password123!", "new_password": "Password123!"},
    )
    assert same.status_code == 400


def test_public_user_unknown_returns_404(api):
    client, _ = api
    assert client.get("/api/v1/users/unknown-uuid").status_code == 404
