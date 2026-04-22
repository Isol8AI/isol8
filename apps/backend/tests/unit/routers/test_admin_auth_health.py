"""Tests for /api/v1/admin/* auth + system-health + audit-viewer endpoints.

TDD-style: these tests are written BEFORE `routers/admin.py` exists. They
should fail (404 from FastAPI for unregistered router, or ImportError on the
patch targets) until Phase C lands the implementation.

The 4 endpoints under test:
- GET /api/v1/admin/me
- GET /api/v1/admin/system/health
- GET /api/v1/admin/actions?target_user_id=...
- GET /api/v1/admin/actions?admin_user_id=...

Auth model: `require_platform_admin` (already-merged, see core/auth.py:242)
gates the router at the dependency level. The async_client fixture overrides
`get_current_user` to return AuthContext(user_id="user_test_123"), so we
toggle access by monkeypatching `settings.PLATFORM_ADMIN_USER_IDS`.
"""

import os
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")


# ---------------------------------------------------------------------------
# Auth gate (5 cases) — every admin endpoint must hide behind require_platform_admin
# ---------------------------------------------------------------------------


class TestAdminAuthGate:
    """The /admin/* surface returns 403 unless the caller's Clerk user_id is
    in the PLATFORM_ADMIN_USER_IDS allowlist."""

    @pytest.mark.asyncio
    async def test_admin_me_403_when_user_not_in_allowlist(self, async_client, monkeypatch):
        """Empty allowlist => 403 with the require_platform_admin detail string."""
        monkeypatch.setattr("core.config.settings.PLATFORM_ADMIN_USER_IDS", "")
        response = await async_client.get("/api/v1/admin/me")
        assert response.status_code == 403
        assert response.json()["detail"] == "Platform admin access required"

    @pytest.mark.asyncio
    async def test_admin_me_200_for_allowlisted_user(self, async_client, monkeypatch):
        """user_test_123 (mock_auth_context default) is in allowlist => 200 with profile."""
        monkeypatch.setattr("core.config.settings.PLATFORM_ADMIN_USER_IDS", "user_test_123")
        response = await async_client.get("/api/v1/admin/me")
        assert response.status_code == 200
        body = response.json()
        assert body["user_id"] == "user_test_123"
        assert body["is_admin"] is True
        # `email` key is always present in the response shape (may be None when
        # the AuthContext didn't carry an email claim).
        assert "email" in body

    @pytest.mark.asyncio
    async def test_admin_system_health_403_for_non_admin(self, async_client, monkeypatch):
        monkeypatch.setattr("core.config.settings.PLATFORM_ADMIN_USER_IDS", "user_someone_else")
        response = await async_client.get("/api/v1/admin/system/health")
        assert response.status_code == 403
        assert response.json()["detail"] == "Platform admin access required"

    @pytest.mark.asyncio
    async def test_admin_actions_403_for_non_admin(self, async_client, monkeypatch):
        monkeypatch.setattr("core.config.settings.PLATFORM_ADMIN_USER_IDS", "")
        response = await async_client.get("/api/v1/admin/actions", params={"target_user_id": "u1"})
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_me_includes_email_when_present(self, app, monkeypatch):
        """When the JWT carried an email claim, /me echoes it back so the
        operator UI can show 'logged in as <email>'."""
        from httpx import ASGITransport, AsyncClient

        from core.auth import AuthContext, get_current_user

        monkeypatch.setattr("core.config.settings.PLATFORM_ADMIN_USER_IDS", "user_test_123")

        async def _mock_user_with_email():
            return AuthContext(user_id="user_test_123", email="admin@isol8.co")

        app.dependency_overrides[get_current_user] = _mock_user_with_email
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.get("/api/v1/admin/me")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json()["email"] == "admin@isol8.co"


# ---------------------------------------------------------------------------
# /admin/system/health (3 cases)
# ---------------------------------------------------------------------------


class TestAdminSystemHealth:
    """GET /api/v1/admin/system/health — thin wrapper around
    `core.services.system_health.get_system_health()`."""

    @pytest.mark.asyncio
    @patch("routers.admin.system_health")
    async def test_system_health_returns_aggregator_result(self, mock_system_health, async_client, monkeypatch):
        """Aggregator result is returned verbatim as the JSON body."""
        monkeypatch.setattr("core.config.settings.PLATFORM_ADMIN_USER_IDS", "user_test_123")
        payload = {
            "upstreams": {"clerk": "ok", "stripe": "ok", "bedrock": "ok", "ddb": "ok"},
            "fleet": {"total": 12, "running": 11, "stopped": 1},
            "background_tasks": {"usage_poller": "alive", "town_sim": "alive"},
            "recent_errors": [],
        }
        mock_system_health.get_system_health = AsyncMock(return_value=payload)

        response = await async_client.get("/api/v1/admin/system/health")

        assert response.status_code == 200
        assert response.json() == payload

    @pytest.mark.asyncio
    @patch("routers.admin.system_health")
    async def test_system_health_never_500s_when_aggregator_returns_partial(
        self, mock_system_health, async_client, monkeypatch
    ):
        """If subsystem checks fail individually the aggregator returns a
        partial dict (with empty/error sections) — the endpoint must NOT
        500. This test pins that contract."""
        monkeypatch.setattr("core.config.settings.PLATFORM_ADMIN_USER_IDS", "user_test_123")
        partial = {
            "upstreams": {"clerk": "error", "stripe": "ok"},
            "fleet": {},
            "background_tasks": {},
            "recent_errors": [{"source": "fleet", "error": "ECS DescribeServices throttled"}],
        }
        mock_system_health.get_system_health = AsyncMock(return_value=partial)

        response = await async_client.get("/api/v1/admin/system/health")

        assert response.status_code == 200
        assert response.json() == partial

    @pytest.mark.asyncio
    @patch("routers.admin.system_health")
    async def test_system_health_calls_aggregator_once_per_request(self, mock_system_health, async_client, monkeypatch):
        """Sanity check: one HTTP call -> one aggregator call (no fan-out, no
        accidental double-await)."""
        monkeypatch.setattr("core.config.settings.PLATFORM_ADMIN_USER_IDS", "user_test_123")
        mock_system_health.get_system_health = AsyncMock(return_value={})

        await async_client.get("/api/v1/admin/system/health")

        mock_system_health.get_system_health.assert_awaited_once()


# ---------------------------------------------------------------------------
# /admin/actions audit viewer (4 cases)
# ---------------------------------------------------------------------------


class TestAdminActionsAuditViewer:
    """GET /api/v1/admin/actions — paginated viewer over the admin actions
    audit log, filtered by either target_user_id or admin_user_id."""

    @pytest.mark.asyncio
    @patch("routers.admin.admin_service")
    async def test_actions_filters_by_target_user_id(self, mock_admin_service, async_client, monkeypatch):
        """`?target_user_id=u1&limit=20` => service called with target_user_id="u1",
        limit=20, admin_user_id=None, cursor=None."""
        monkeypatch.setattr("core.config.settings.PLATFORM_ADMIN_USER_IDS", "user_test_123")
        mock_admin_service.get_actions_audit = AsyncMock(return_value={"items": [], "cursor": None})

        response = await async_client.get(
            "/api/v1/admin/actions",
            params={"target_user_id": "u1", "limit": 20},
        )

        assert response.status_code == 200
        mock_admin_service.get_actions_audit.assert_awaited_once_with(
            target_user_id="u1",
            admin_user_id=None,
            limit=20,
            cursor=None,
        )

    @pytest.mark.asyncio
    @patch("routers.admin.admin_service")
    async def test_actions_filters_by_admin_user_id(self, mock_admin_service, async_client, monkeypatch):
        """`?admin_user_id=admin_x` routes to the admin_user_id kwarg, leaving
        target_user_id None."""
        monkeypatch.setattr("core.config.settings.PLATFORM_ADMIN_USER_IDS", "user_test_123")
        mock_admin_service.get_actions_audit = AsyncMock(return_value={"items": [{"id": "evt1"}], "cursor": None})

        response = await async_client.get("/api/v1/admin/actions", params={"admin_user_id": "admin_x"})

        assert response.status_code == 200
        kwargs = mock_admin_service.get_actions_audit.await_args.kwargs
        assert kwargs["admin_user_id"] == "admin_x"
        assert kwargs["target_user_id"] is None

    @pytest.mark.asyncio
    @patch("routers.admin.admin_service")
    async def test_actions_returns_400_when_neither_filter_provided(
        self, mock_admin_service, async_client, monkeypatch
    ):
        """When the service raises ValueError (its way of signalling 'pick a
        filter'), the router translates to 400."""
        monkeypatch.setattr("core.config.settings.PLATFORM_ADMIN_USER_IDS", "user_test_123")
        mock_admin_service.get_actions_audit = AsyncMock(
            side_effect=ValueError("must filter by target_user_id or admin_user_id")
        )

        response = await async_client.get("/api/v1/admin/actions")

        assert response.status_code == 400

    @pytest.mark.asyncio
    @patch("routers.admin.admin_service")
    async def test_actions_threads_cursor_for_pagination(self, mock_admin_service, async_client, monkeypatch):
        """`?cursor=abc&limit=5` is passed through unchanged so the next page
        can be fetched."""
        monkeypatch.setattr("core.config.settings.PLATFORM_ADMIN_USER_IDS", "user_test_123")
        mock_admin_service.get_actions_audit = AsyncMock(return_value={"items": [], "cursor": "next_cur"})

        response = await async_client.get(
            "/api/v1/admin/actions",
            params={"target_user_id": "u1", "cursor": "abc", "limit": 5},
        )

        assert response.status_code == 200
        kwargs = mock_admin_service.get_actions_audit.await_args.kwargs
        assert kwargs["cursor"] == "abc"
        assert kwargs["limit"] == 5
        # Body propagates the next-page cursor untouched.
        assert response.json()["cursor"] == "next_cur"


# ---------------------------------------------------------------------------
# Audit-of-views (3 cases) — these endpoints must NOT write audit rows
# ---------------------------------------------------------------------------


class TestAdminEndpointsDoNotAuditThemselves:
    """`/me`, `/system/health`, and `/actions` are operator-side reads that
    must NOT create admin_actions audit entries:

    - `/me` is a self-identity probe, not a user view.
    - `/system/health` reads aggregate fleet state, not a single user.
    - `/actions` viewing the audit log itself would create an infinite trail.

    The contract: `admin_actions_repo.create` is never called for these three.
    Per-user-view endpoints (added in later phases) DO audit; these don't.
    """

    @pytest.mark.asyncio
    @patch("routers.admin.admin_actions_repo")
    async def test_admin_me_does_not_audit(self, mock_repo, async_client, monkeypatch):
        monkeypatch.setattr("core.config.settings.PLATFORM_ADMIN_USER_IDS", "user_test_123")
        mock_repo.create = AsyncMock()

        response = await async_client.get("/api/v1/admin/me")

        assert response.status_code == 200
        mock_repo.create.assert_not_called()

    @pytest.mark.asyncio
    @patch("routers.admin.admin_actions_repo")
    @patch("routers.admin.system_health")
    async def test_system_health_does_not_audit(self, mock_system_health, mock_repo, async_client, monkeypatch):
        monkeypatch.setattr("core.config.settings.PLATFORM_ADMIN_USER_IDS", "user_test_123")
        mock_system_health.get_system_health = AsyncMock(return_value={})
        mock_repo.create = AsyncMock()

        response = await async_client.get("/api/v1/admin/system/health")

        assert response.status_code == 200
        mock_repo.create.assert_not_called()

    @pytest.mark.asyncio
    @patch("routers.admin.admin_actions_repo")
    @patch("routers.admin.admin_service")
    async def test_actions_does_not_audit(self, mock_admin_service, mock_repo, async_client, monkeypatch):
        monkeypatch.setattr("core.config.settings.PLATFORM_ADMIN_USER_IDS", "user_test_123")
        mock_admin_service.get_actions_audit = AsyncMock(return_value={"items": [], "cursor": None})
        mock_repo.create = AsyncMock()

        response = await async_client.get("/api/v1/admin/actions", params={"target_user_id": "u1"})

        assert response.status_code == 200
        mock_repo.create.assert_not_called()
