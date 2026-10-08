"""Auction HTTP tests without MongoDB Atlas; real routers and services are used."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_user, get_optional_current_user
from app.api.routes.auctions import get_auction_repository
from app.main import app
from app.models.auction import Auction
from app.models.common import utc_now
from app.models.user import User
from app.services.auction_service import effective_status


class FakeAuctionRepository:
    def __init__(self):
        self.auctions: dict[str, Auction] = {}
        self.last_public_filter: dict | None = None

    async def create(self, auction: Auction) -> Auction:
        self.auctions[auction.id] = auction
        return auction

    async def get_by_id(self, auction_id: str) -> Auction | None:
        return self.auctions.get(auction_id)

    async def update_draft(self, auction_id: str, seller_id: str, changes: dict):
        auction = self.auctions.get(auction_id)
        if auction is None or auction.seller_id != seller_id or auction.status != "draft":
            return None
        updated = Auction.model_validate(
            {**auction.model_dump(mode="python"), **changes, "updated_at": utc_now()}
        )
        self.auctions[auction_id] = updated
        return updated

    async def publish(self, auction_id: str, seller_id: str, now):
        auction = self.auctions.get(auction_id)
        if auction is None or auction.seller_id != seller_id or auction.status != "draft":
            return None
        if auction.ends_at <= now:
            return None
        auction.status = "active"
        auction.updated_at = now
        return auction

    async def cancel(self, auction_id, seller_id, expected_status, expected_price, now):
        auction = self.auctions.get(auction_id)
        if (auction is None or auction.seller_id != seller_id
                or auction.status != expected_status or auction.current_price != expected_price
                or auction.leader_id is not None):
            return None
        if auction.status == "active" and auction.ends_at <= now:
            return None
        auction.status = "cancelled"
        auction.updated_at = now
        return auction

    def _public_results(self, query):
        now = utc_now()
        result = []
        for auction in self.auctions.values():
            state = effective_status(auction, now)
            if "status" in query and state != ("scheduled" if query.get("starts_at", {}).get("$gt") else "active"):
                continue
            if "$or" in query and state != "finished":
                continue
            if "category" in query and auction.category != query["category"]:
                continue
            price = query.get("current_price", {})
            if "$gte" in price and auction.current_price < price["$gte"]:
                continue
            if "$lte" in price and auction.current_price > price["$lte"]:
                continue
            if "$and" in query:
                import re
                pattern = query["$and"][0]["$or"][0]["title"]["$regex"]
                if not re.search(pattern, auction.title + " " + auction.description, re.I):
                    continue
            result.append(auction)
        return result

    async def count_public(self, query):
        self.last_public_filter = query
        return len(self._public_results(query))

    async def find_public(self, query, sort_field, sort_direction, skip, limit):
        result = self._public_results(query)
        result.sort(key=lambda a: (getattr(a, sort_field), a.id), reverse=sort_direction < 0)
        return result[skip:skip + limit]

    async def count_by_seller(self, seller_id):
        return len([a for a in self.auctions.values() if a.seller_id == seller_id])

    async def find_by_seller(self, seller_id, skip, limit):
        result = [a for a in self.auctions.values() if a.seller_id == seller_id]
        result.sort(key=lambda a: a.created_at, reverse=True)
        return result[skip:skip + limit]


@pytest.fixture
def api():
    owner = User(username="OwnerOne", email="owner@example.com", password_hash="hash")
    other = User(username="OtherUser", email="other@example.com", password_hash="hash")
    repo = FakeAuctionRepository()
    current = {"user": owner}
    app.dependency_overrides[get_auction_repository] = lambda: repo
    app.dependency_overrides[get_current_user] = lambda: current["user"]
    app.dependency_overrides[get_optional_current_user] = lambda: current["user"]
    client = TestClient(app)  # No lifespan: MongoDB Atlas is not used.
    try:
        yield client, repo, current, owner, other
    finally:
        client.close()
        app.dependency_overrides.clear()


def auction_payload(**changes):
    data = {
        "title": "Mechanical Keyboard",
        "description": "New in box",
        "category": "electronics",
        "starting_price": 100,
        "min_bid_step": 10,
        "starts_at": (utc_now() + timedelta(minutes=10)).isoformat(),
        "ends_at": (utc_now() + timedelta(days=2)).isoformat(),
    }
    data.update(changes)
    return data


def create(client, **changes):
    result = client.post("/api/v1/auctions", json=auction_payload(**changes))
    assert result.status_code == 201, result.text
    return result.json()


def test_create_draft_sets_owner_and_price(api):
    client, repo, _, owner, _ = api
    result = create(client, category="  ELECTRONICS  ")
    assert result["seller_id"] == owner.id
    assert result["status"] == "draft"
    assert result["current_price"] == 100
    assert result["category"] == "electronics"
    assert result["effective_status"] == "draft"
    assert repo.auctions[result["id"]].leader_id is None


def test_cannot_inject_owner_or_bid_state(api):
    client, *_ = api
    for illegal in ("seller_id", "current_price", "leader_id", "status"):
        response = client.post("/api/v1/auctions", json=auction_payload(**{illegal: "forged"}))
        assert response.status_code == 422, (illegal, response.text)


def test_draft_is_private_until_published(api):
    client, _, current, _, other = api
    auction = create(client)
    current["user"] = other
    response = client.get(f"/api/v1/auctions/{auction['id']}")
    assert response.status_code == 404
    current["user"] = None
    assert client.get(f"/api/v1/auctions/{auction['id']}").status_code == 404


def test_update_draft_and_initial_price(api):
    client, _, _, _, _ = api
    auction = create(client)
    response = client.patch(
        f"/api/v1/auctions/{auction['id']}",
        json={"title": "Another Keyboard", "starting_price": 150},
    )
    assert response.status_code == 200, response.text
    assert response.json()["current_price"] == 150
    assert response.json()["title"] == "Another Keyboard"


def test_update_rejects_mismatched_times(api):
    client, *_ = api
    auction = create(client)
    response = client.patch(
        f"/api/v1/auctions/{auction['id']}",
        json={"ends_at": (utc_now() + timedelta(minutes=1)).isoformat()},
    )
    assert response.status_code == 422


def test_update_draft_rejects_protected_fields_and_empty_patch(api):
    client, *_ = api
    auction = create(client)
    for payload in ({}, {"leader_id": "fake"}, {"title": None}):
        response = client.patch(f"/api/v1/auctions/{auction['id']}", json=payload)
        assert response.status_code == 422, response.text


def test_only_owner_can_edit_publish_or_cancel(api):
    client, _, current, _, other = api
    auction = create(client)
    current["user"] = other
    base = f"/api/v1/auctions/{auction['id']}"
    assert client.patch(base, json={"title": "Another Title"}).status_code == 403
    assert client.post(base + "/publish").status_code == 403
    assert client.post(base + "/cancel").status_code == 403


def test_publish_and_public_detail(api):
    client, _, current, _, other = api
    auction = create(client)
    base = f"/api/v1/auctions/{auction['id']}"
    response = client.post(base + "/publish")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "active"
    assert response.json()["effective_status"] == "scheduled"
    current["user"] = other
    assert client.get(base).status_code == 200
    assert client.patch(base, json={"starting_price": 1}).status_code == 403


def test_published_auction_cannot_edit_or_publish_twice(api):
    client, *_ = api
    auction = create(client)
    base = f"/api/v1/auctions/{auction['id']}"
    assert client.post(base + "/publish").status_code == 200
    assert client.patch(base, json={"description": "Changed"}).status_code == 409
    assert client.post(base + "/publish").status_code == 409


def test_cancel_draft_and_published_without_bids(api):
    client, *_ = api
    draft = create(client)
    base = f"/api/v1/auctions/{draft['id']}"
    assert client.post(base + "/cancel").json()["status"] == "cancelled"
    assert client.post(base + "/publish").status_code == 409
    published = create(client)
    base2 = f"/api/v1/auctions/{published['id']}"
    assert client.post(base2 + "/publish").status_code == 200
    assert client.post(base2 + "/cancel").json()["status"] == "cancelled"


def test_auction_with_bid_cannot_cancel(api):
    client, repo, *_ = api
    auction = create(client)
    repo.auctions[auction["id"]].leader_id = "bidder-id"
    response = client.post(f"/api/v1/auctions/{auction['id']}/cancel")
    assert response.status_code == 409


def test_catalog_filter_search_and_pagination(api):
    client, _, *_ = api
    first = create(client, title="Wooden Keyboard", starting_price=40)
    second = create(client, title="Metal Keyboard", starting_price=70)
    create(client, title="History Book", category="books", starting_price=25)
    for auction in (first, second):
        assert client.post(f"/api/v1/auctions/{auction['id']}/publish").status_code == 200
    url = "/api/v1/auctions?status=scheduled&search=keyboard&min_price=40&page_size=1&page=2"
    response = client.get(url)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] == 2
    assert data["pages"] == 2
    assert len(data["items"]) == 1
    assert data["page"] == 2


def test_catalog_rejects_invalid_filters_and_escapes_regex(api):
    client, repo, *_ = api
    assert client.get("/api/v1/auctions?min_price=200&max_price=100").status_code == 422
    assert client.get("/api/v1/auctions?page=0").status_code == 422
    assert client.get("/api/v1/auctions?sort_by=password_hash").status_code == 422
    assert client.get("/api/v1/auctions?search=.*").status_code == 200
    assert repo.last_public_filter["$and"][0]["$or"][0]["title"]["$regex"] == r"\.\*"


def test_my_auctions_includes_drafts(api):
    client, _, current, owner, other = api
    create(client)
    create(client, title="Another Item")
    current["user"] = other
    create(client, title="Other Item")
    current["user"] = owner
    result = client.get("/api/v1/users/me/auctions")
    assert result.status_code == 200, result.text
    assert result.json()["total"] == 2
    assert {item["status"] for item in result.json()["items"]} == {"draft"}


def test_categories_and_404(api):
    client, *_ = api
    assert "electronics" in client.get("/api/v1/auctions/categories").json()
    assert client.get("/api/v1/auctions/missing-uuid").status_code == 404


def test_unauthenticated_cannot_create_or_view_my_auctions(api):
    from app.api.dependencies import get_user_repository

    client, _, current, *_ = api
    # Test the real authorization dependency, not the authorized fixture override.
    app.dependency_overrides.pop(get_current_user)
    app.dependency_overrides[get_user_repository] = lambda: object()
    try:
        assert client.post("/api/v1/auctions", json=auction_payload()).status_code == 401
        assert client.get("/api/v1/users/me/auctions").status_code == 401
    finally:
        app.dependency_overrides[get_current_user] = lambda: current["user"]
        app.dependency_overrides.pop(get_user_repository, None)
