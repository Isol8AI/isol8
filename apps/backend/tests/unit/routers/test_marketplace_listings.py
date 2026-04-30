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
