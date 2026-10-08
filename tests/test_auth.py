
import pytest
from fastapi.testclient import TestClient
from pymongo.errors import DuplicateKeyError

from app.api.dependencies import get_user_repository
from app.core.security import verify_password
from app.main import app
from app.models.user import User


class FakeUserRepository:
    def __init__(self):
        self.users: list[User] = []
        self.fail_on_create = False

    async def get_by_email(self, email: str):
        return next(
            (
                user for user in self.users
                if str(user.email) == email
            ),
            None
        )

    async def get_by_username(self, username: str):
        return next(
            (
                user for user in self.users
                if user.username == username
            ),
            None
        )

    async def create(self, user: User):
        if self.fail_on_create:
            raise DuplicateKeyError("Duplicate key")

        self.users.append(user)
        return user


@pytest.fixture
def api():
    repository = FakeUserRepository()

    # Підміняємо справжній MongoDB Repository
    app.dependency_overrides[get_user_repository] = (
        lambda: repository
    )

    # Без context manager TestClient не запускає lifespan,
    # тому тест не підключається до MongoDB Atlas
    client = TestClient(app)

    try:
        yield client, repository
    finally:
        client.close()
        app.dependency_overrides.clear()


def make_user_data(**overrides):
    data = {
        "username": "Oleksii",
        "email": "oleksii@example.com",
        "password": "StrongPassword123!"
    }

    data.update(overrides)
    return data


def test_register_success(api):
    client, repository = api

    response = client.post(
        "/api/v1/auth/register",
        json=make_user_data()
    )

    assert response.status_code == 201

    result = response.json()

    assert result["username"] == "Oleksii"
    assert result["email"] == "oleksii@example.com"
    assert result["role"] == "user"
    assert "id" in result

    # Конфіденційні дані не повертаються
    assert "password" not in result
    assert "password_hash" not in result

    # У репозиторії збережено саме хеш
    saved_user = repository.users[0]

    assert saved_user.password_hash != "StrongPassword123!"
    assert verify_password(
        "StrongPassword123!",
        saved_user.password_hash
    )


def test_duplicate_email(api):
    client, _ = api

    data = make_user_data()

    first_response = client.post(
        "/api/v1/auth/register",
        json=data
    )

    second_response = client.post(
        "/api/v1/auth/register",
        json=make_user_data(
            username="AnotherUser",
            email="OLEKSII@EXAMPLE.COM"
        )
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 409


def test_duplicate_username(api):
    client, _ = api

    client.post(
        "/api/v1/auth/register",
        json=make_user_data()
    )

    response = client.post(
        "/api/v1/auth/register",
        json=make_user_data(
            email="another@example.com"
        )
    )

    assert response.status_code == 409


@pytest.mark.parametrize(
    "invalid_data",
    [
        {"email": "not-an-email"},
        {"username": "ab"},
        {"username": "   "},
        {"password": "123"}
    ]
)
def test_register_invalid_data(api, invalid_data):
    client, repository = api

    response = client.post(
        "/api/v1/auth/register",
        json=make_user_data(**invalid_data)
    )

    assert response.status_code == 422
    assert len(repository.users) == 0


def test_cannot_assign_admin_role(api):
    client, _ = api

    data = make_user_data(role="admin")

    response = client.post(
        "/api/v1/auth/register",
        json=data
    )

    assert response.status_code == 422


def test_duplicate_key_during_insert(api):
    client, repository = api

    # Імітація конфлікту унікального індексу MongoDB
    repository.fail_on_create = True

    response = client.post(
        "/api/v1/auth/register",
        json=make_user_data()
    )

    assert response.status_code == 409
    assert repository.users == []


def test_username_is_trimmed(api):
    client, _ = api

    response = client.post(
        "/api/v1/auth/register",
        json=make_user_data(username="  Oleksii  ")
    )

    assert response.status_code == 201
    assert response.json()["username"] == "Oleksii"
