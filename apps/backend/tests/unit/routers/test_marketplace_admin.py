"""Tests for marketplace_admin router."""

import os

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")

from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from core.auth import AuthContext, get_current_user  # noqa: E402


@pytest.fixture
def client():
    from main import app

    return TestClient(app)


def _admit_admin(app):
    """Override get_current_user so the caller has an @isol8.co email."""
    app.dependency_overrides[get_current_user] = lambda: AuthContext(user_id="user_admin_123", email="admin@isol8.co")


def test_admin_queue_requires_admin(client):
    resp = client.get("/api/v1/admin/marketplace/listings")
    assert resp.status_code in (401, 403)


def test_approve_requires_admin(client):
    resp = client.post("/api/v1/admin/marketplace/listings/l1/approve")
    assert resp.status_code in (401, 403)


def test_admin_takedown_endpoint_requires_admin(client):
    resp = client.post(
        "/api/v1/admin/marketplace/listings/l1/takedown",
        json={"reason": "policy", "basis_md": "x" * 20},
    )
    assert resp.status_code in (401, 403)


def test_list_takedowns_requires_admin(client):
    resp = client.get("/api/v1/admin/marketplace/takedowns")
    assert resp.status_code in (401, 403)


def test_admin_takedown_endpoint_creates_and_grants(client):
    """Full request shape: admin POSTs reason+basis_md → service called →
    response carries takedown_id + affected_purchases."""
    from main import app

    _admit_admin(app)

    expected = {
        "takedown_id": "td-uuid-1",
        "listing_id": "l-1",
        "affected_purchases": 4,
    }
    with patch(
        "routers.marketplace_admin.takedown_service.execute_admin_initiated_takedown",
        new=AsyncMock(return_value=expected),
    ) as mock_service:
        resp = client.post(
            "/api/v1/admin/marketplace/listings/l-1/takedown",
            json={
                "reason": "fraud",
                "basis_md": "Listing impersonates an unrelated brand. Reported by Stripe radar.",
            },
        )

    app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "taken_down"
    assert body["takedown_id"] == "td-uuid-1"
    assert body["affected_purchases"] == 4
    assert body["listing_id"] == "l-1"

    mock_service.assert_awaited_once()
    call_kwargs = mock_service.await_args.kwargs
    assert call_kwargs["listing_id"] == "l-1"
    assert call_kwargs["reason"] == "fraud"
    assert call_kwargs["basis_md"].startswith("Listing impersonates")
    assert call_kwargs["decided_by"] == "user_admin_123"


def test_reject_reads_notes_from_request_body(client):
    """Regression: reject must accept notes as a JSON body field, not a
    query param. The admin UI sends ``{ notes }`` in JSON; if `notes`
    binds to a query param, every UI reject 422s (Codex P1 on PR #517,
    commit 23bdc518).
    """
    from main import app

    _admit_admin(app)

    with patch(
        "routers.marketplace_admin.marketplace_service.reject",
        new=AsyncMock(return_value={"status": "draft", "rejection_notes": "incomplete docs"}),
    ) as mock_service:
        resp = client.post(
            "/api/v1/admin/marketplace/listings/l-1/reject",
            json={"notes": "incomplete docs"},
        )

    app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    mock_service.assert_awaited_once()
    assert mock_service.await_args.kwargs["notes"] == "incomplete docs"


def test_admin_takedown_404s_for_nonexistent_listing(client):
    """Regression: the takedown cascade's ``_listings_table().update_item``
    used to upsert a fake listing for nonexistent IDs. Now guarded with
    ``ConditionExpression="attribute_exists(listing_id)"`` and surfaced as
    404 (Codex P2 on PR #517, commit 23bdc518).
    """
    from main import app

    from core.services.takedown_service import ListingNotFoundError

    _admit_admin(app)

    with patch(
        "routers.marketplace_admin.takedown_service.execute_admin_initiated_takedown",
        new=AsyncMock(side_effect=ListingNotFoundError("listing l-ghost v1 does not exist")),
    ):
        resp = client.post(
            "/api/v1/admin/marketplace/listings/l-ghost/takedown",
            json={
                "reason": "policy",
                "basis_md": "Long enough basis to pass min_length=10 validator.",
            },
        )

    app.dependency_overrides.clear()

    assert resp.status_code == 404, resp.text
    assert "l-ghost" in resp.json()["detail"]


def test_admin_takedown_validates_basis_md_length(client):
    """basis_md < 10 chars rejected so the audit log always has a real reason."""
    from main import app

    _admit_admin(app)

    resp = client.post(
        "/api/v1/admin/marketplace/listings/l-1/takedown",
        json={"reason": "policy", "basis_md": "short"},
    )
    app.dependency_overrides.clear()
    assert resp.status_code == 422


def test_admin_takedowns_list_returns_recent_first(client):
    """Scan-based audit log view sorts by decided_at desc."""
    from main import app

    _admit_admin(app)

    fake_table = MagicMock()
    fake_table.scan.return_value = {
        "Items": [
            {"takedown_id": "old", "decided_at": "2026-01-01T00:00:00Z"},
            {"takedown_id": "newest", "decided_at": "2026-04-01T00:00:00Z"},
            {"takedown_id": "mid", "decided_at": "2026-03-15T00:00:00Z"},
            {"takedown_id": "no-decided-at"},  # defensive: missing field sinks
        ]
    }
    fake_resource = MagicMock()
    fake_resource.Table.return_value = fake_table

    with patch("routers.marketplace_admin.boto3.resource", return_value=fake_resource):
        resp = client.get("/api/v1/admin/marketplace/takedowns")

    app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert [r["takedown_id"] for r in items] == ["newest", "mid", "old", "no-decided-at"]


def test_admin_takedowns_list_paginates_full_scan(client):
    """Audit-log view must page through ALL scan results before sorting.

    Pins the pagination contract: a `LastEvaluatedKey` on page 1 forces a
    follow-up scan with `ExclusiveStartKey`, and items from BOTH pages must
    end up in the merged + sorted output. Catches regressions that re-add
    a `Limit=N` cap (which would silently return "newest of an arbitrary
    subset" once the table holds >N rows).
    """
    from main import app

    _admit_admin(app)

    fake_table = MagicMock()
    page1 = {
        "Items": [
            {"takedown_id": "p1-old", "decided_at": "2026-01-01T00:00:00Z"},
            {"takedown_id": "p1-mid", "decided_at": "2026-02-15T00:00:00Z"},
        ],
        "LastEvaluatedKey": {"listing_id": "l-cursor", "takedown_id": "td-cursor"},
    }
    page2 = {
        "Items": [
            {"takedown_id": "p2-newest", "decided_at": "2026-04-01T00:00:00Z"},
            {"takedown_id": "p2-older", "decided_at": "2025-12-01T00:00:00Z"},
        ],
        # No LastEvaluatedKey → end of pagination.
    }
    fake_table.scan.side_effect = [page1, page2]
    fake_resource = MagicMock()
    fake_resource.Table.return_value = fake_table

    with patch("routers.marketplace_admin.boto3.resource", return_value=fake_resource):
        resp = client.get("/api/v1/admin/marketplace/takedowns")

    app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text

    # Both pages were fetched.
    assert fake_table.scan.call_count == 2
    # Page 1: no ExclusiveStartKey, no Limit cap.
    page1_kwargs = fake_table.scan.call_args_list[0].kwargs
    assert "ExclusiveStartKey" not in page1_kwargs
    assert "Limit" not in page1_kwargs
    # Page 2: ExclusiveStartKey forwarded from page 1's LastEvaluatedKey.
    page2_kwargs = fake_table.scan.call_args_list[1].kwargs
    assert page2_kwargs["ExclusiveStartKey"] == {
        "listing_id": "l-cursor",
        "takedown_id": "td-cursor",
    }

    # All four items merged + sorted by decided_at desc.
    items = resp.json()["items"]
    assert [r["takedown_id"] for r in items] == [
        "p2-newest",
        "p1-mid",
        "p1-old",
        "p2-older",
    ]
