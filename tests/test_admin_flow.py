"""HTTP-level administration tests without MongoDB or real JWT signing."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_user, get_user_repository
from app.api.routes.admin import get_admin_repository
from app.main import app
from app.models.auction import Auction
from app.models.common import utc_now
from app.models.user import User
from app.services.admin_service import auction_query, user_query


class FakeAdminRepository:
    def __init__(self, users: list[User], auctions: list[Auction]):
        self.users = {user.id: user for user in users}
        self.auctions = {auction.id: auction for auction in auctions}
        self.bids: list[dict] = []
        self.audit: list[dict] = []
        self.fail_cas = False
        self.fail_audit = False

    async def get_user(self, user_id):
        return self.users.get(user_id)

    async def update_user_active(self, user_id, expected_active, new_active):
        user = self.users.get(user_id)
        if user is None or user.role != "user" or user.is_active != expected_active:
            return None
        user.is_active = new_active
        user.token_version += 1
        user.updated_at = utc_now()
        return user

    def _matching_users(self, query):
        import re

        def matches(user):
            if "role" in query and user.role != query["role"]:
                return False
            if "is_active" in query and user.is_active != query["is_active"]:
                return False
            if "$or" in query:
                pattern = query["$or"][0]["username"]["$regex"]
                return bool(re.search(pattern, user.username + " " + str(user.email), re.IGNORECASE))
            return True

        return [user for user in self.users.values() if matches(user)]

    async def count_users(self, query):
        return len(self._matching_users(query))

    async def list_users(self, query, skip, limit):
        return self._matching_users(query)[skip:skip + limit]

    async def get_auction(self, auction_id):
        return self.auctions.get(auction_id)

    def _matching_auctions(self, query):
        now = utc_now()
        from app.services.auction_service import effective_status

        result = []
        for a in self.auctions.values():
            state = effective_status(a, now)
            if query.get("status") == "draft" and state != "draft":
                continue
            if query.get("status") == "cancelled" and state != "cancelled":
                continue
            if query.get("status") == "active":
                expected = "scheduled" if "$gt" in query.get("starts_at", {}) else "active"
                if state != expected:
                    continue
            if "$or" in query and state != "finished":
                continue
            if "seller_id" in query and a.seller_id != query["seller_id"]:
                continue
            if "category" in query and a.category != query["category"]:
                continue
            if "$and" in query:
                import re

                pattern = query["$and"][0]["$or"][0]["title"]["$regex"]
                if not re.search(pattern, a.title + " " + a.description, re.IGNORECASE):
                    continue
            result.append(a)
        return result

    async def count_auctions(self, query):
        return len(self._matching_auctions(query))

    async def list_auctions(self, query, skip, limit):
        return self._matching_auctions(query)[skip:skip + limit]

    async def has_bids(self, auction_id):
        return any(b["auction_id"] == auction_id for b in self.bids)

    async def cancel_no_bid_auction(self, auction_id, expected_status, starting_price, now):
        auction = self.auctions.get(auction_id)
        if self.fail_cas or auction is None:
            return None
        if auction.status != expected_status:
            return None
        if auction.leader_id is not None or auction.starting_price != starting_price:
            return None
        if auction.current_price != starting_price:
            return None
        if auction.status == "active" and auction.ends_at <= now:
            return None
        auction.status = "cancelled"
        auction.updated_at = now
        return auction

    async def count_bids(self):
        return len(self.bids)

    async def add_audit(self, *, actor_id, action, target_id, reason):
        if self.fail_audit:
            raise RuntimeError("audit unavailable")
        self.audit.append({
            "_id": f"audit-{len(self.audit) + 1}",
            "actor_id": actor_id,
            "action": action,
            "target_id": target_id,
            "reason": reason,
            "created_at": utc_now(),
        })

    async def count_audit(self, query):
        return len(await self.list_audit(query, 0, 10000))

    async def list_audit(self, query, skip, limit):
        docs = self.audit
        if "action" in query:
            docs = [doc for doc in docs if doc["action"] == query["action"]]
        return list(reversed(docs))[skip:skip + limit]


@pytest.fixture
def admin_api():
    admin = User(username="Moderator", email="admin@example.com", password_hash="hash", role="admin")
    seller = User(username="SellerJoe", email="seller@example.com", password_hash="hash")
    bidder = User(username="BidderOne", email="bidder@example.com", password_hash="hash")
    other_admin = User(username="AnotherAdmin", email="another@example.com", password_hash="hash", role="admin")
    draft = Auction(
        seller_id=seller.id, title="Draft Keyboard", category="electronics",
        starting_price=50, current_price=50, ends_at=utc_now() + timedelta(days=2),
        status="draft",
    )
    active = Auction(
        seller_id=seller.id, title="Live Laptop", category="electronics",
        starting_price=100, current_price=100,
        starts_at=utc_now() - timedelta(hours=1),
        ends_at=utc_now() + timedelta(days=2), status="active",
    )
    scheduled = Auction(
        seller_id=seller.id, title="Scheduled Auction", category="books",
        starting_price=20, current_price=20,
        starts_at=utc_now() + timedelta(hours=2),
        ends_at=utc_now() + timedelta(days=2), status="active",
    )
    repo = FakeAdminRepository([admin, seller, bidder, other_admin], [draft, active, scheduled])
    user = {"current": admin}
    app.dependency_overrides[get_current_user] = lambda: user["current"]
    app.dependency_overrides[get_admin_repository] = lambda: repo
    client = TestClient(app)  # Lifespan is skipped, so MongoDB is not contacted.
    try:
        yield client, repo, user, admin, seller, bidder, other_admin, draft, active, scheduled
    finally:
        client.close()
        app.dependency_overrides.clear()


def reason(value="Repeated prohibited content"):
    return {"reason": value}


def test_admin_endpoints_registered():
    api = app.openapi()
    for path in (
        "/api/v1/admin/users",
        "/api/v1/admin/users/{user_id}",
        "/api/v1/admin/users/{user_id}/block",
        "/api/v1/admin/users/{user_id}/unblock",
        "/api/v1/admin/auctions",
        "/api/v1/admin/auctions/{auction_id}",
        "/api/v1/admin/auctions/{auction_id}/cancel",
        "/api/v1/admin/statistics",
        "/api/v1/admin/audit-logs",
    ):
        assert path in api["paths"]


def test_non_admin_cannot_access_any_admin_route(admin_api):
    client, repo, current, _, seller, _, _, _, active, _ = admin_api
    current["current"] = seller
    requests = [
        ("get", "/api/v1/admin/users", None),
        ("get", f"/api/v1/admin/users/{seller.id}", None),
        ("post", f"/api/v1/admin/users/{seller.id}/block", reason()),
        ("post", f"/api/v1/admin/users/{seller.id}/unblock", reason()),
        ("get", "/api/v1/admin/auctions", None),
        ("get", f"/api/v1/admin/auctions/{active.id}", None),
        ("post", f"/api/v1/admin/auctions/{active.id}/cancel", reason()),
        ("get", "/api/v1/admin/statistics", None),
        ("get", "/api/v1/admin/audit-logs", None),
    ]
    for method, path, payload in requests:
        response = getattr(client, method)(path, json=payload) if payload else getattr(client, method)(path)
        assert response.status_code == 403, (path, response.text)
    assert repo.audit == []


def test_missing_token_returns_401(admin_api):
    client, _, _, *_ = admin_api
    app.dependency_overrides.pop(get_current_user)
    app.dependency_overrides[get_user_repository] = lambda: object()
    assert client.get("/api/v1/admin/users").status_code == 401


def test_list_users_filter_and_password_hash_not_exposed(admin_api):
    client, *_ = admin_api
    response = client.get("/api/v1/admin/users?search=seller&role=user&page_size=1")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] == 1 and data["pages"] == 1
    assert data["items"][0]["username"] == "SellerJoe"
    assert "password_hash" not in data["items"][0]
    assert "token_version" not in data["items"][0]


def test_admin_get_user_404_and_detail(admin_api):
    client, _repo, _current, _admin, seller, *_ = admin_api
    assert client.get(f"/api/v1/admin/users/{seller.id}").json()["id"] == seller.id
    assert client.get("/api/v1/admin/users/missing").status_code == 404


def test_block_and_unblock_revokes_tokens_and_audits(admin_api):
    client, repo, _, _, seller, *_ = admin_api
    old_version = seller.token_version
    path = f"/api/v1/admin/users/{seller.id}"
    blocked = client.post(path + "/block", json=reason())
    assert blocked.status_code == 200, blocked.text
    assert blocked.json()["is_active"] is False
    assert repo.users[seller.id].token_version == old_version + 1
    assert client.post(path + "/block", json=reason()).status_code == 409
    unblocked = client.post(path + "/unblock", json=reason("Appeal was accepted"))
    assert unblocked.status_code == 200
    assert unblocked.json()["is_active"] is True
    assert repo.users[seller.id].token_version == old_version + 2
    assert [x["action"] for x in repo.audit] == ["user.block", "user.unblock"]
    assert repo.audit[0]["reason"] == "Repeated prohibited content"


def test_cannot_block_self_or_other_admin(admin_api):
    client, _, _, admin, _seller, _bidder, another_admin, *_ = admin_api
    assert client.post(f"/api/v1/admin/users/{admin.id}/block", json=reason()).status_code == 409
    assert client.post(f"/api/v1/admin/users/{another_admin.id}/block", json=reason()).status_code == 409
    assert client.post("/api/v1/admin/users/missing/block", json=reason()).status_code == 404


def test_reason_validation_and_unknown_fields(admin_api):
    client, _, _, _, seller, *_ = admin_api
    url = f"/api/v1/admin/users/{seller.id}/block"
    for payload in ({"reason": "    "}, {"reason": "short"}, {"reason": "Valid long reason", "is_active": False}):
        assert client.post(url, json=payload).status_code == 422


def test_admin_can_list_drafts_and_filter_scheduled(admin_api):
    client, _, _, _, _, _, _, draft, active, scheduled = admin_api
    all_lots = client.get("/api/v1/admin/auctions")
    assert all_lots.status_code == 200
    assert all_lots.json()["total"] == 3
    assert {i["id"] for i in all_lots.json()["items"]} == {draft.id, active.id, scheduled.id}
    assert client.get("/api/v1/admin/auctions?status=draft").json()["total"] == 1
    assert client.get("/api/v1/admin/auctions?status=scheduled").json()["total"] == 1
    assert client.get("/api/v1/admin/auctions?status=active").json()["total"] == 1
    assert client.get("/api/v1/admin/auctions?status=active&page=0").status_code == 422


def test_admin_can_get_private_auction(admin_api):
    client, _, _, _, _, _, _, draft, *_ = admin_api
    response = client.get(f"/api/v1/admin/auctions/{draft.id}")
    assert response.status_code == 200
    assert response.json()["status"] == "draft"
    assert client.get("/api/v1/admin/auctions/missing").status_code == 404


def test_admin_cancel_draft_and_active(admin_api):
    client, repo, _, _, _, _, _, draft, active, _ = admin_api
    a = client.post(f"/api/v1/admin/auctions/{draft.id}/cancel", json=reason())
    assert a.status_code == 200, a.text
    b = client.post(f"/api/v1/admin/auctions/{active.id}/cancel", json=reason())
    assert b.status_code == 200, b.text
    assert a.json()["status"] == b.json()["status"] == "cancelled"
    assert [x["action"] for x in repo.audit] == ["auction.cancel", "auction.cancel"]
    assert client.post(f"/api/v1/admin/auctions/{draft.id}/cancel", json=reason()).status_code == 409


def test_admin_cannot_cancel_auction_with_bid_history(admin_api):
    client, repo, _, _, _, _, _, _draft, active, _ = admin_api
    repo.bids.append({"auction_id": active.id})
    result = client.post(f"/api/v1/admin/auctions/{active.id}/cancel", json=reason())
    assert result.status_code == 409
    assert repo.auctions[active.id].status == "active"
    assert repo.audit == []


def test_admin_cannot_cancel_current_leader_or_price_changed(admin_api):
    client, _repo, _, _, _, _, _, _draft, active, _ = admin_api
    active.leader_id = "bidder-id"
    assert client.post(f"/api/v1/admin/auctions/{active.id}/cancel", json=reason()).status_code == 409
    active.leader_id = None
    active.current_price = 120
    assert client.post(f"/api/v1/admin/auctions/{active.id}/cancel", json=reason()).status_code == 409


def test_admin_cancel_cas_conflict(admin_api):
    client, repo, _, _, _, _, _, _draft, active, _ = admin_api
    repo.fail_cas = True
    assert client.post(f"/api/v1/admin/auctions/{active.id}/cancel", json=reason()).status_code == 409


def test_statistics_and_audit_pagination(admin_api):
    client, repo, _, _, seller, _, _, _draft, active, _scheduled = admin_api
    repo.bids.extend([{"auction_id": active.id}, {"auction_id": active.id}])
    stats = client.get("/api/v1/admin/statistics")
    assert stats.status_code == 200
    data = stats.json()
    assert data["users_total"] == 4
    assert data["users_active"] == 4
    assert data["auctions_total"] == 3
    assert data["auctions_draft"] == 1
    assert data["auctions_active"] == 1
    assert data["auctions_scheduled"] == 1
    assert data["bids_total"] == 2
    client.post(f"/api/v1/admin/users/{seller.id}/block", json=reason())
    logs = client.get("/api/v1/admin/audit-logs?action=user.block")
    assert logs.status_code == 200, logs.text
    assert logs.json()["total"] == 1
    assert logs.json()["items"][0]["action"] == "user.block"
    assert client.get("/api/v1/admin/audit-logs?page=0").status_code == 422


def test_admin_audit_error_does_not_report_successful_write_as_failure(admin_api):
    client, repo, _, _, seller, *_ = admin_api
    repo.fail_audit = True
    response = client.post(f"/api/v1/admin/users/{seller.id}/block", json=reason())
    assert response.status_code == 200
    assert seller.is_active is False


def test_user_search_escapes_regex_and_finished_filter():
    query = user_query("(name).*", "user", False)
    assert query["$or"][0]["username"]["$regex"] == r"\(name\)\.\*"
    query = auction_query(utc_now(), "finished", "(book).*", None, None)
    assert "$or" in query and "$and" in query
