"""Tests for POST /api/v1/orgs/{org_id}/invitations — Gate A."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import AuthContext
from routers import orgs


@pytest.fixture
def app():
    """Mount the orgs router for isolated testing."""
    app = FastAPI()
    app.include_router(orgs.router, prefix="/api/v1/orgs")
    return app


@pytest.fixture
def admin_auth():
    """Auth context for an admin of org_test."""
    return AuthContext(
        user_id="user_admin",
        org_id="org_test",
        org_role="org:admin",
        org_slug="testorg",
        org_permissions=["org:sys_memberships:manage"],
        email="admin@example.com",
    )


@pytest.fixture
def member_auth():
    """Auth context for a basic member of org_test."""
    return AuthContext(
        user_id="user_member",
        org_id="org_test",
        org_role="org:member",
        org_slug="testorg",
        org_permissions=[],
        email="member@example.com",
    )


@pytest.fixture
def personal_auth():
    """Auth context for a personal user (no org)."""
    return AuthContext(user_id="user_personal", email="personal@example.com")


def _override_auth(app, ctx):
    """Override get_current_user dependency for the duration of one test."""
    from core.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: ctx


def test_invite_to_email_with_no_clerk_user_succeeds(app, admin_auth):
    _override_auth(app, admin_auth)
    with patch("routers.orgs.clerk_admin") as mock_clerk, patch("routers.orgs.billing_repo") as mock_billing:
        mock_clerk.find_user_by_email = AsyncMock(return_value=None)
        mock_clerk.create_organization_invitation = AsyncMock(return_value={"id": "orginv_abc"})
        client = TestClient(app)
        resp = client.post(
            "/api/v1/orgs/org_test/invitations",
            json={"email": "newperson@example.com", "role": "org:member"},
        )
    assert resp.status_code == 201
    assert resp.json() == {"invitation_id": "orginv_abc"}
    mock_billing.get_by_owner_id.assert_not_called()
    mock_clerk.create_organization_invitation.assert_awaited_once()


def test_invite_to_email_with_clerk_user_no_billing_succeeds(app, admin_auth):
    _override_auth(app, admin_auth)
    with patch("routers.orgs.clerk_admin") as mock_clerk, patch("routers.orgs.billing_repo") as mock_billing:
        mock_clerk.find_user_by_email = AsyncMock(return_value={"id": "user_existing"})
        mock_billing.get_by_owner_id = AsyncMock(return_value=None)
        mock_clerk.create_organization_invitation = AsyncMock(return_value={"id": "orginv_def"})
        client = TestClient(app)
        resp = client.post(
            "/api/v1/orgs/org_test/invitations",
            json={"email": "existing@example.com", "role": "org:member"},
        )
    assert resp.status_code == 201
    mock_clerk.create_organization_invitation.assert_awaited_once()


def test_invite_to_email_with_inactive_billing_succeeds(app, admin_auth):
    """Canceled or expired personal subs no longer count as active tenancies."""
    _override_auth(app, admin_auth)
    with patch("routers.orgs.clerk_admin") as mock_clerk, patch("routers.orgs.billing_repo") as mock_billing:
        mock_clerk.find_user_by_email = AsyncMock(return_value={"id": "user_existing"})
        mock_billing.get_by_owner_id = AsyncMock(
            return_value={"owner_id": "user_existing", "subscription_status": "canceled"}
        )
        mock_clerk.create_organization_invitation = AsyncMock(return_value={"id": "orginv_ghi"})
        client = TestClient(app)
        resp = client.post(
            "/api/v1/orgs/org_test/invitations",
            json={"email": "ex-customer@example.com", "role": "org:member"},
        )
    assert resp.status_code == 201


@pytest.mark.parametrize("status", ["active", "trialing"])
def test_invite_to_email_with_active_personal_returns_409(app, admin_auth, status):
    _override_auth(app, admin_auth)
    with patch("routers.orgs.clerk_admin") as mock_clerk, patch("routers.orgs.billing_repo") as mock_billing:
        mock_clerk.find_user_by_email = AsyncMock(return_value={"id": "user_existing"})
        mock_billing.get_by_owner_id = AsyncMock(
            return_value={"owner_id": "user_existing", "subscription_status": status}
        )
        mock_clerk.create_organization_invitation = AsyncMock()
        client = TestClient(app)
        resp = client.post(
            "/api/v1/orgs/org_test/invitations",
            json={"email": "subscriber@example.com", "role": "org:member"},
        )
    assert resp.status_code == 409
    body = resp.json()
    assert body["detail"]["code"] == "personal_user_exists"
    assert "subscriber@example.com" in body["detail"]["message"]
    mock_clerk.create_organization_invitation.assert_not_awaited()


def test_non_admin_caller_returns_403(app, member_auth):
    _override_auth(app, member_auth)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/orgs/org_test/invitations",
        json={"email": "nope@example.com", "role": "org:member"},
    )
    assert resp.status_code == 403


def test_personal_caller_returns_403(app, personal_auth):
    """Personal users have no org_id — require_org_admin lets personal pass-through;
    the org_id mismatch check below catches them."""
    _override_auth(app, personal_auth)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/orgs/org_test/invitations",
        json={"email": "nope@example.com", "role": "org:member"},
    )
    assert resp.status_code == 403


def test_caller_in_different_org_returns_403(app, admin_auth):
    """Admin of org_test cannot invite to org_other."""
    _override_auth(app, admin_auth)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/orgs/org_other/invitations",
        json={"email": "x@example.com", "role": "org:member"},
    )
    assert resp.status_code == 403


def test_default_role_is_member(app, admin_auth):
    """Omitting role in the body defaults to org:member."""
    _override_auth(app, admin_auth)
    captured = {}

    async def _capture(**kwargs):
        captured.update(kwargs)
        return {"id": "orginv_default"}

    with patch("routers.orgs.clerk_admin") as mock_clerk, patch("routers.orgs.billing_repo"):
        mock_clerk.find_user_by_email = AsyncMock(return_value=None)
        mock_clerk.create_organization_invitation = AsyncMock(side_effect=_capture)
        client = TestClient(app)
        resp = client.post(
            "/api/v1/orgs/org_test/invitations",
            json={"email": "default@example.com"},
        )
    assert resp.status_code == 201
    assert captured["role"] == "org:member"
