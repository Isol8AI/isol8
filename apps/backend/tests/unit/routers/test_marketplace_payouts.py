"""Tests for marketplace_payouts router."""

import os

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client():
    from main import app

    return TestClient(app)


def test_onboard_requires_auth(client):
    resp = client.post("/api/v1/marketplace/payouts/onboard")
    assert resp.status_code in (401, 403)


def test_dashboard_requires_auth(client):
    resp = client.get("/api/v1/marketplace/payouts/dashboard")
    assert resp.status_code in (401, 403)
