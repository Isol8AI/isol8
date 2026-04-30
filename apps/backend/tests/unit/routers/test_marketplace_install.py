"""Tests for marketplace_install router."""

import os

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")

from unittest.mock import AsyncMock, patch  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from core.services.license_service import ValidationResult  # noqa: E402


@pytest.fixture
def client():
    from main import app

    return TestClient(app)


@patch(
    "routers.marketplace_install.marketplace_service.get_by_id",
    new=AsyncMock(return_value={"slug": "x", "manifest_sha256": "sha-1"}),
)
@patch(
    "routers.marketplace_install.license_service.validate",
    new=AsyncMock(
        return_value=ValidationResult(status="valid", listing_id="l1", listing_version=1, entitlement_version_floor=1),
    ),
)
@patch("routers.marketplace_install._presigned_url", new=AsyncMock(return_value=("https://signed.example/x", "sha-1")))
def test_install_validate_returns_signed_url(client):
    resp = client.get(
        "/api/v1/marketplace/install/validate",
        headers={"Authorization": "Bearer iml_xxx"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["download_url"] == "https://signed.example/x"


@patch(
    "routers.marketplace_install.license_service.validate",
    new=AsyncMock(
        return_value=ValidationResult(status="revoked", reason="refunded"),
    ),
)
def test_install_validate_revoked_returns_401(client):
    resp = client.get(
        "/api/v1/marketplace/install/validate",
        headers={"Authorization": "Bearer iml_revoked"},
    )
    assert resp.status_code == 401


def test_install_validate_missing_header_returns_401(client):
    resp = client.get("/api/v1/marketplace/install/validate")
    assert resp.status_code == 401
