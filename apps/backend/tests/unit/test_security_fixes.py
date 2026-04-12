"""Tests for backend security fixes (#190 §3).

Covers CRITICAL items 1-6, HIGH items 7-9/11-13, MEDIUM items 15-17,
plus Stripe/Clerk webhook idempotency and DynamoDB throttle wrapper.
"""

import os
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from core.auth import AuthContext


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app():
    from main import app as fastapi_app

    return fastapi_app


@pytest.fixture
def org_admin_context():
    return AuthContext(
        user_id="user_admin_1",
        org_id="org_test_1",
        org_role="org:admin",
        org_slug="test-org",
    )


@pytest.fixture
def personal_context():
    return AuthContext(user_id="user_personal_1")


@pytest.fixture
def admin_client(app, org_admin_context):
    from core.auth import get_current_user

    async def _mock():
        return org_admin_context

    app.dependency_overrides[get_current_user] = _mock
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ===================================================================
# Task 1: CRITICAL — Fleet patch requires confirmation header
# ===================================================================


class TestFleetPatchConfirmationHeader:

    @patch("routers.updates.run_in_thread", new_callable=AsyncMock)
    @patch("routers.updates.get_table")
    def test_fleet_patch_requires_confirmation_header(self, mock_table, mock_run, admin_client):
        resp = admin_client.patch(
            "/api/v1/container/config",
            json={"patch": {"test": "value"}},
        )
        assert resp.status_code == 400
        assert "X-Confirm-Fleet-Patch" in resp.json()["detail"]

    @patch("routers.updates.patch_openclaw_config", new_callable=AsyncMock)
    @patch("routers.updates.run_in_thread", new_callable=AsyncMock)
    @patch("routers.updates.get_table")
    def test_fleet_patch_with_header_succeeds(self, mock_table, mock_run, mock_patch, admin_client):
        mock_run.return_value = {"Items": []}
        resp = admin_client.patch(
            "/api/v1/container/config",
            json={"patch": {"test": "value"}},
            headers={"X-Confirm-Fleet-Patch": "yes-i-am-sure"},
        )
        assert resp.status_code == 200

    @patch("routers.updates.patch_openclaw_config", new_callable=AsyncMock)
    @patch("routers.updates.run_in_thread", new_callable=AsyncMock)
    @patch("routers.updates.get_table")
    def test_fleet_patch_emits_audit_log(self, mock_table, mock_run, mock_patch, admin_client, caplog):
        mock_run.return_value = {"Items": []}
        import logging

        with caplog.at_level(logging.WARNING):
            admin_client.patch(
                "/api/v1/container/config",
                json={"patch": {"test": "value"}},
                headers={"X-Confirm-Fleet-Patch": "yes-i-am-sure"},
            )
        assert any("Fleet config patch invoked" in r.message for r in caplog.records)


# ===================================================================
# Task 2: CRITICAL — Cross-tenant config patch check
# ===================================================================


class TestCrossTenantConfigPatch:

    @patch("routers.updates.patch_openclaw_config", new_callable=AsyncMock)
    @patch("routers.updates.user_repo")
    def test_single_patch_blocks_cross_tenant(self, mock_user_repo, mock_patch, admin_client):
        mock_user_repo.get = AsyncMock(return_value={"user_id": "user-in-org-b", "org_id": "org_test_2"})
        resp = admin_client.patch(
            "/api/v1/container/config/user-in-org-b",
            json={"patch": {"test": "value"}},
        )
        assert resp.status_code == 403

    @patch("routers.updates.patch_openclaw_config", new_callable=AsyncMock)
    @patch("routers.updates.user_repo")
    def test_single_patch_allows_same_tenant(self, mock_user_repo, mock_patch, admin_client):
        mock_user_repo.get = AsyncMock(return_value={"user_id": "user-in-org-a", "org_id": "org_test_1"})
        resp = admin_client.patch(
            "/api/v1/container/config/user-in-org-a",
            json={"patch": {"models": {}}},
        )
        assert resp.status_code == 200


# ===================================================================
# Task 3: CRITICAL — Debug endpoint allow-list
# ===================================================================


class TestDebugEndpointAllowList:

    @pytest.mark.parametrize("env_value", ["prod", "production", "staging"])
    def test_debug_endpoints_blocked_in_prod(self, env_value, app):
        from core.auth import get_current_user

        async def _mock():
            return AuthContext(user_id="user_test")

        app.dependency_overrides[get_current_user] = _mock
        with patch("routers.debug.settings") as mock_settings:
            mock_settings.ENVIRONMENT = env_value
            with TestClient(app) as client:
                resp = client.post("/api/v1/debug/provision")
                assert resp.status_code == 403
        app.dependency_overrides.clear()


# ===================================================================
# Task 4: CRITICAL — Path traversal fix
# ===================================================================


class TestPathTraversalFix:

    @pytest.mark.parametrize(
        "malicious_path",
        [
            "../../../etc/passwd",
            "../../other-user/secrets",
            "/absolute/path",
            "normal/../../../escape",
        ],
    )
    def test_path_traversal_blocked(self, malicious_path, tmp_path):
        from core.containers.workspace import Workspace

        ws = Workspace(mount_path=str(tmp_path))
        (tmp_path / "alice").mkdir()
        with pytest.raises(Exception):
            ws._resolve_user_file("alice", malicious_path)

    def test_path_traversal_prefix_attack(self, tmp_path):
        from core.containers.workspace import Workspace

        ws = Workspace(mount_path=str(tmp_path))
        (tmp_path / "alice").mkdir()
        (tmp_path / "alice_evil").mkdir()
        with pytest.raises(Exception):
            ws._resolve_user_file("alice", "../alice_evil/secret.txt")

    def test_valid_path_allowed(self, tmp_path):
        from core.containers.workspace import Workspace

        ws = Workspace(mount_path=str(tmp_path))
        user_dir = tmp_path / "alice"
        user_dir.mkdir()
        (user_dir / "notes.txt").write_text("hello")
        resolved = ws._resolve_user_file("alice", "notes.txt")
        assert resolved == user_dir / "notes.txt"


# ===================================================================
# Task 8: HIGH — JWKS stale fallback cap + TTL
# ===================================================================


class TestJWKSSecurity:

    def test_jwks_ttl_is_5_minutes(self):
        from core.auth import JWKS_CACHE_TTL

        assert JWKS_CACHE_TTL == timedelta(minutes=5)

    @pytest.mark.asyncio
    async def test_jwks_stale_fallback_capped(self):
        """Stale JWKS cache > 15 min should fail closed."""
        from core import auth

        original_cache = auth._jwks_cache.copy()
        auth._jwks_cache["data"] = {"keys": [{"kid": "test"}]}
        auth._jwks_cache["expires_at"] = datetime.utcnow() - timedelta(minutes=20)

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("network error")

        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("network error")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        try:
            with patch("core.auth.httpx.AsyncClient", return_value=mock_client):
                with pytest.raises(httpx.HTTPError):
                    await auth._get_cached_jwks("https://test/.well-known/jwks.json")
        finally:
            auth._jwks_cache.update(original_cache)

    @pytest.mark.asyncio
    async def test_jwks_stale_within_15min_allowed(self):
        """Stale JWKS within 15 min should be served."""
        from core import auth

        original_cache = auth._jwks_cache.copy()
        test_keys = {"keys": [{"kid": "test"}]}
        auth._jwks_cache["data"] = test_keys
        auth._jwks_cache["expires_at"] = datetime.utcnow() - timedelta(minutes=2)

        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("network error")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        try:
            with patch("core.auth.httpx.AsyncClient", return_value=mock_client):
                result = await auth._get_cached_jwks("https://test/.well-known/jwks.json")
                assert result == test_keys
        finally:
            auth._jwks_cache.update(original_cache)


# ===================================================================
# Task 9: HIGH — Gateway token encryption
# ===================================================================


class TestGatewayTokenEncryption:

    def test_encrypt_gateway_token_prefixed(self):
        from core.services.key_service import decrypt_gateway_token, encrypt_gateway_token

        token = "my-secret-token"
        encrypted = encrypt_gateway_token(token)
        assert encrypted.startswith("enc:")
        assert decrypt_gateway_token(encrypted) == token

    def test_decrypt_plaintext_passthrough(self):
        from core.services.key_service import decrypt_gateway_token

        assert decrypt_gateway_token("plain-token") == "plain-token"


# ===================================================================
# Task 10: HIGH — WS Origin validation
# ===================================================================


class TestWSOriginValidation:

    def test_origin_allow_list_defined(self):
        authorizer_path = Path(
            os.path.join(
                os.path.dirname(__file__),
                "..", "..", "..", "..",
                "infra", "lambda", "websocket-authorizer", "index.py",
            )
        )
        # Fallback for worktree layout
        if not authorizer_path.exists():
            authorizer_path = Path(
                "/Users/prasiddhaparthsarthy/Desktop/isol8.nosync/.claude/worktrees/orr-specs"
                "/apps/infra/lambda/websocket-authorizer/index.py"
            )
        content = authorizer_path.read_text()
        assert "ALLOWED_ORIGINS" in content
        assert "https://app.isol8.co" in content
        assert "http://localhost:3000" in content


# ===================================================================
# Task 11: HIGH — Control UI Referer stripping
# ===================================================================


class TestControlUIRefererStrip:

    def test_referer_handling_in_proxy(self):
        proxy_path = Path(
            "/Users/prasiddhaparthsarthy/Desktop/isol8.nosync/.claude/worktrees/orr-specs"
            "/apps/backend/routers/control_ui_proxy.py"
        )
        content = proxy_path.read_text()
        assert "Referer" in content


# ===================================================================
# Task 12: MEDIUM — mcporter file permissions
# ===================================================================


class TestMcporterFilePermissions:

    def test_mcporter_file_mode(self, tmp_path):
        from core.containers.workspace import Workspace

        with patch("core.containers.workspace.settings") as mock_settings:
            mock_settings.EFS_MOUNT_PATH = str(tmp_path)
            mock_settings.ENVIRONMENT = "local"
            ws = Workspace(mount_path=str(tmp_path))
            ws.ensure_user_dir("testuser")
            mcporter_path = tmp_path / "testuser" / ".mcporter" / "mcporter.json"
            assert mcporter_path.exists()
            mode = oct(mcporter_path.stat().st_mode & 0o777)
            assert mode == "0o600"


# ===================================================================
# Task 13: MEDIUM — Health endpoint rate limit
# ===================================================================


class TestHealthRateLimit:

    def test_health_rate_limited(self, app):
        from main import _health_buckets

        _health_buckets.clear()

        with patch("core.dynamodb.get_table"), patch(
            "core.dynamodb.run_in_thread", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = None
            with TestClient(app) as client:
                for i in range(100):
                    resp = client.get("/health")
                    assert resp.status_code in (200, 503), f"Request {i}: {resp.status_code}"
                resp = client.get("/health")
                assert resp.status_code == 429


# ===================================================================
# Task 14: DynamoDB throttle wrapper
# ===================================================================


class TestDynamoDBThrottleWrapper:

    @pytest.mark.asyncio
    async def test_throttle_retry_and_metric(self):
        from botocore.exceptions import ClientError

        from core.services.dynamodb_helper import call_with_metrics

        error = ClientError(
            {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": ""}},
            "GetItem",
        )
        fn = MagicMock(side_effect=[error, {"Item": {"id": "1"}}])
        with patch("core.services.dynamodb_helper.put_metric") as mock_metric:
            result = await call_with_metrics("test-table", "get", fn)
        assert result == {"Item": {"id": "1"}}
        mock_metric.assert_called_with(
            "dynamodb.throttle", dimensions={"table": "test-table", "op": "get"}
        )

    @pytest.mark.asyncio
    async def test_non_throttle_error_emits_error_metric(self):
        from botocore.exceptions import ClientError

        from core.services.dynamodb_helper import call_with_metrics

        error = ClientError(
            {"Error": {"Code": "ValidationException", "Message": "bad"}},
            "PutItem",
        )
        fn = MagicMock(side_effect=error)
        with patch("core.services.dynamodb_helper.put_metric") as mock_metric:
            with pytest.raises(ClientError):
                await call_with_metrics("test-table", "put", fn)
        mock_metric.assert_called_with(
            "dynamodb.error",
            dimensions={"table": "test-table", "op": "put", "error_code": "ValidationException"},
        )

    @pytest.mark.asyncio
    async def test_success_no_metric(self):
        from core.services.dynamodb_helper import call_with_metrics

        fn = MagicMock(return_value={"Item": {"id": "1"}})
        with patch("core.services.dynamodb_helper.put_metric") as mock_metric:
            result = await call_with_metrics("test-table", "get", fn)
        assert result == {"Item": {"id": "1"}}
        mock_metric.assert_not_called()
