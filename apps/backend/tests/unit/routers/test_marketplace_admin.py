"""Tests for marketplace_admin router."""

import os

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client():
    from main import app

    return TestClient(app)


def test_admin_queue_requires_admin(client):
    resp = client.get("/api/v1/admin/marketplace/listings")
    assert resp.status_code in (401, 403)


def test_approve_requires_admin(client):
    resp = client.post("/api/v1/admin/marketplace/listings/l1/approve")
    assert resp.status_code in (401, 403)


def test_takedown_requires_admin(client):
    resp = client.post("/api/v1/admin/marketplace/takedowns/l1?takedown_id=t1")
    assert resp.status_code in (401, 403)
