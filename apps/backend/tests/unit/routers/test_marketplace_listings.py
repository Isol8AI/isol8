"""Tests for marketplace_listings router."""

import os

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")

from unittest.mock import AsyncMock, patch  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client():
    from main import app

    return TestClient(app)


@patch("routers.marketplace_listings.marketplace_search.browse", new=AsyncMock(return_value=[]))
def test_browse_listings_returns_200(client):
    resp = client.get("/api/v1/marketplace/listings")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


@patch("routers.marketplace_listings.marketplace_search.search", new=AsyncMock(return_value=[]))
def test_search_with_tags_param(client):
    resp = client.get("/api/v1/marketplace/listings?tags=sales,outreach")
    assert resp.status_code == 200


def test_create_draft_requires_auth(client):
    """Without a Clerk JWT, create draft must 401."""
    resp = client.post(
        "/api/v1/marketplace/listings",
        json={
            "slug": "x",
            "name": "x",
            "description_md": "x",
            "format": "openclaw",
            "delivery_method": "cli",
            "price_cents": 0,
            "tags": [],
        },
    )
    assert resp.status_code in (401, 403)


# ----------------------------------------------------------------------
# Auth helpers for the new endpoints
# ----------------------------------------------------------------------


@pytest.fixture
def auth_override():
    from core.auth import AuthContext, get_current_user
    from main import app

    async def _mock():
        return AuthContext(user_id="user_seller_abc")

    app.dependency_overrides[get_current_user] = _mock
    yield "user_seller_abc"
    app.dependency_overrides.pop(get_current_user, None)


# ----------------------------------------------------------------------
# /seller-eligibility
# ----------------------------------------------------------------------


def test_seller_eligibility_paid_tier(client, auth_override):
    with patch(
        "routers.marketplace_listings.billing_repo.get_by_owner_id",
        new=AsyncMock(return_value={"tier": "pro"}),
    ):
        resp = client.get("/api/v1/marketplace/seller-eligibility")
    assert resp.status_code == 200
    body = resp.json()
    assert body["tier"] == "pro"
    assert body["can_sell_skillmd"] is True
    assert body["can_sell_openclaw"] is True
    assert body["reason"] is None


def test_seller_eligibility_free_tier_blocks_openclaw(client, auth_override):
    with patch(
        "routers.marketplace_listings.billing_repo.get_by_owner_id",
        new=AsyncMock(return_value={"tier": "free"}),
    ):
        resp = client.get("/api/v1/marketplace/seller-eligibility")
    assert resp.status_code == 200
    body = resp.json()
    assert body["tier"] == "free"
    assert body["can_sell_skillmd"] is True
    assert body["can_sell_openclaw"] is False
    assert "Starter" in body["reason"]


def test_seller_eligibility_no_billing_record(client, auth_override):
    with patch(
        "routers.marketplace_listings.billing_repo.get_by_owner_id",
        new=AsyncMock(return_value=None),
    ):
        resp = client.get("/api/v1/marketplace/seller-eligibility")
    assert resp.status_code == 200
    body = resp.json()
    assert body["tier"] == "none"
    assert body["can_sell_openclaw"] is False


# ----------------------------------------------------------------------
# /my-agents
# ----------------------------------------------------------------------


def test_my_agents_empty_when_no_workspace(client, auth_override):
    from unittest.mock import MagicMock

    fake_ws = MagicMock()
    fake_ws.list_agents = MagicMock(return_value=[])
    with patch("routers.marketplace_listings.get_workspace", return_value=fake_ws):
        resp = client.get("/api/v1/marketplace/my-agents")
    assert resp.status_code == 200
    assert resp.json() == {"items": []}


def test_my_agents_returns_agent_list(client, auth_override, tmp_path):
    from unittest.mock import MagicMock

    user_root = tmp_path / "user_seller_abc"
    (user_root / "agents" / "agent-a").mkdir(parents=True)
    (user_root / "agents" / "agent-b").mkdir(parents=True)

    fake_ws = MagicMock()
    fake_ws.list_agents = MagicMock(return_value=["agent-a", "agent-b"])
    fake_ws.user_path = MagicMock(return_value=user_root)
    with patch("routers.marketplace_listings.get_workspace", return_value=fake_ws):
        resp = client.get("/api/v1/marketplace/my-agents")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 2
    assert {i["agent_id"] for i in items} == {"agent-a", "agent-b"}


# ----------------------------------------------------------------------
# /listings/{id}/artifact-from-agent — tier gate
# ----------------------------------------------------------------------


def test_artifact_from_agent_blocks_free_tier(client, auth_override):
    with patch(
        "routers.marketplace_listings.billing_repo.get_by_owner_id",
        new=AsyncMock(return_value={"tier": "free"}),
    ):
        resp = client.post(
            "/api/v1/marketplace/listings/some-listing-id/artifact-from-agent",
            json={"agent_id": "my-agent-001"},
        )
    assert resp.status_code == 403
    body = resp.json()
    assert "current_tier" in body["detail"]
    assert body["detail"]["current_tier"] == "free"
