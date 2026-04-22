"""Tests for PATCH /api/v1/config router."""

import os
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")

from core.auth import AuthContext  # noqa: E402


@pytest.fixture
def client():
    from main import app

    return TestClient(app)


def _personal_auth(user_id: str = "user_personal") -> AuthContext:
    return AuthContext(user_id=user_id)


def _org_admin_auth(user_id: str = "user_admin", org_id: str = "org_1") -> AuthContext:
    return AuthContext(user_id=user_id, org_id=org_id, org_role="org:admin")


def _org_member_auth(user_id: str = "user_member", org_id: str = "org_1") -> AuthContext:
    return AuthContext(user_id=user_id, org_id=org_id, org_role="org:member")


def _patch_auth(auth: AuthContext):
    """Override the FastAPI dependency that returns the auth context."""
    from core.auth import get_current_user
    from main import app

    app.dependency_overrides[get_current_user] = lambda: auth
    return lambda: app.dependency_overrides.pop(get_current_user, None)


def _mock_billing(tier: str):
    return patch(
        "routers.config.billing_repo.get_by_owner_id",
        AsyncMock(return_value={"plan_tier": tier}),
    )


def test_patch_config_personal_user_succeeds(client):
    cleanup = _patch_auth(_personal_auth())
    try:
        with patch("routers.config.patch_openclaw_config", AsyncMock()) as mock_patch, _mock_billing("starter"):
            resp = client.patch(
                "/api/v1/config",
                json={"patch": {"channels": {"telegram": {"enabled": True}}}},
            )
        assert resp.status_code == 200
        mock_patch.assert_awaited_once()
        call_args = mock_patch.call_args
        assert call_args[0][0] == "user_personal"
    finally:
        cleanup()


def test_patch_config_org_admin_succeeds(client):
    cleanup = _patch_auth(_org_admin_auth())
    try:
        with patch("routers.config.patch_openclaw_config", AsyncMock()) as mock_patch, _mock_billing("pro"):
            resp = client.patch(
                "/api/v1/config",
                json={"patch": {"channels": {"telegram": {"enabled": True}}}},
            )
        assert resp.status_code == 200
        mock_patch.assert_awaited_once()
        assert mock_patch.call_args[0][0] == "org_1"
    finally:
        cleanup()


def test_patch_config_org_member_rejected(client):
    cleanup = _patch_auth(_org_member_auth())
    try:
        with patch("routers.config.patch_openclaw_config", AsyncMock()) as mock_patch, _mock_billing("pro"):
            resp = client.patch(
                "/api/v1/config",
                json={"patch": {"channels": {"telegram": {"enabled": True}}}},
            )
        assert resp.status_code == 403
        mock_patch.assert_not_called()
    finally:
        cleanup()


def test_patch_config_free_tier_channels_rejected(client):
    cleanup = _patch_auth(_personal_auth())
    try:
        with patch("routers.config.patch_openclaw_config", AsyncMock()) as mock_patch, _mock_billing("free"):
            resp = client.patch(
                "/api/v1/config",
                json={"patch": {"channels": {"telegram": {"enabled": True}}}},
            )
        assert resp.status_code == 403
        assert "channels_require_paid_tier" in resp.json().get("detail", "")
        mock_patch.assert_not_called()
    finally:
        cleanup()


def test_patch_config_free_tier_non_channels_succeeds(client):
    cleanup = _patch_auth(_personal_auth())
    try:
        with patch("routers.config.patch_openclaw_config", AsyncMock()) as mock_patch, _mock_billing("free"):
            resp = client.patch(
                "/api/v1/config",
                json={"patch": {"tools": {"profile": "full"}}},
            )
        assert resp.status_code == 200
        mock_patch.assert_awaited_once()
    finally:
        cleanup()


def test_patch_config_validation_rejects_non_dict_patch(client):
    cleanup = _patch_auth(_personal_auth())
    try:
        resp = client.patch(
            "/api/v1/config",
            json={"patch": "not a dict"},
        )
        assert resp.status_code == 422  # Pydantic rejects
    finally:
        cleanup()


def test_patch_config_rejects_token_collision(client):
    """Pasting a token already assigned to a different agent returns 409."""
    cleanup = _patch_auth(_personal_auth())
    try:
        existing_cfg = {
            "channels": {
                "telegram": {
                    "accounts": {
                        "main": {"botToken": "SHARED_TOKEN"},
                    },
                },
            },
        }
        with (
            patch("routers.config.patch_openclaw_config", AsyncMock()),
            patch(
                "routers.config.read_openclaw_config_from_efs",
                AsyncMock(return_value=existing_cfg),
            ),
            _mock_billing("pro"),
        ):
            resp = client.patch(
                "/api/v1/config",
                json={
                    "patch": {
                        "channels": {
                            "telegram": {
                                "accounts": {
                                    "sales": {"botToken": "SHARED_TOKEN"},
                                },
                            },
                        },
                    },
                },
            )
        assert resp.status_code == 409
        assert "token_already_assigned_to_other_agent" in resp.json().get("detail", "")
    finally:
        cleanup()


def test_patch_config_allows_overwriting_own_agent_token(client):
    """Updating the SAME agent's token is fine (overwrite)."""
    cleanup = _patch_auth(_personal_auth())
    try:
        existing_cfg = {
            "channels": {
                "telegram": {
                    "accounts": {
                        "main": {"botToken": "OLD_TOKEN"},
                    },
                },
            },
        }
        with (
            patch("routers.config.patch_openclaw_config", AsyncMock()) as mock_patch,
            patch(
                "routers.config.read_openclaw_config_from_efs",
                AsyncMock(return_value=existing_cfg),
            ),
            patch("routers.config.append_to_openclaw_config_list", AsyncMock()),
            _mock_billing("pro"),
        ):
            resp = client.patch(
                "/api/v1/config",
                json={
                    "patch": {
                        "channels": {
                            "telegram": {
                                "accounts": {
                                    "main": {"botToken": "NEW_TOKEN"},
                                },
                            },
                        },
                    },
                },
            )
        assert resp.status_code == 200
        mock_patch.assert_awaited_once()
    finally:
        cleanup()


def test_patch_config_autoadds_routing_binding_for_new_account(client):
    """A PATCH that adds channels.<provider>.accounts.<agent_id> must also
    append a matching bindings entry so OpenClaw routes the channel to the
    right agent. Without this the channel defaults to the `main` agent."""
    cleanup = _patch_auth(_org_admin_auth())
    try:
        with (
            patch("routers.config.patch_openclaw_config", AsyncMock()),
            patch("routers.config.read_openclaw_config_from_efs", AsyncMock(return_value={})),
            patch("routers.config.append_to_openclaw_config_list", AsyncMock()) as mock_append,
            _mock_billing("starter"),
        ):
            resp = client.patch(
                "/api/v1/config",
                json={
                    "patch": {
                        "channels": {
                            "telegram": {
                                "enabled": True,
                                "accounts": {
                                    "ray": {"botToken": "T", "dmPolicy": "pairing"},
                                },
                            },
                        },
                    },
                },
            )
        assert resp.status_code == 200
        mock_append.assert_awaited_once_with(
            "org_1",
            ["bindings"],
            {
                "type": "route",
                "agentId": "ray",
                "match": {"channel": "telegram", "accountId": "ray"},
            },
        )
    finally:
        cleanup()


def test_patch_config_autoadds_binding_per_account_across_providers(client):
    """Multiple accounts across providers each get their own binding."""
    cleanup = _patch_auth(_org_admin_auth())
    try:
        with (
            patch("routers.config.patch_openclaw_config", AsyncMock()),
            patch("routers.config.read_openclaw_config_from_efs", AsyncMock(return_value={})),
            patch("routers.config.append_to_openclaw_config_list", AsyncMock()) as mock_append,
            _mock_billing("starter"),
        ):
            resp = client.patch(
                "/api/v1/config",
                json={
                    "patch": {
                        "channels": {
                            "telegram": {"accounts": {"ray": {"botToken": "T1"}}},
                            "discord": {"accounts": {"sales": {"token": "D1"}}},
                        },
                    },
                },
            )
        assert resp.status_code == 200
        assert mock_append.await_count == 2
        calls = {call.args[2]["agentId"]: call.args[2] for call in mock_append.await_args_list}
        assert calls["ray"]["match"] == {"channel": "telegram", "accountId": "ray"}
        assert calls["sales"]["match"] == {"channel": "discord", "accountId": "sales"}
    finally:
        cleanup()


def test_patch_config_no_binding_append_when_patch_is_not_channels(client):
    """Non-channel patches must not trigger bindings append."""
    cleanup = _patch_auth(_personal_auth())
    try:
        with (
            patch("routers.config.patch_openclaw_config", AsyncMock()),
            patch("routers.config.append_to_openclaw_config_list", AsyncMock()) as mock_append,
            _mock_billing("free"),
        ):
            resp = client.patch(
                "/api/v1/config",
                json={"patch": {"tools": {"profile": "full"}}},
            )
        assert resp.status_code == 200
        mock_append.assert_not_called()
    finally:
        cleanup()


def test_patch_config_no_binding_append_when_channels_touched_without_accounts(client):
    """`channels.telegram.enabled` alone should not trigger a bindings append
    (no accounts were introduced)."""
    cleanup = _patch_auth(_org_admin_auth())
    try:
        with (
            patch("routers.config.patch_openclaw_config", AsyncMock()),
            patch("routers.config.read_openclaw_config_from_efs", AsyncMock(return_value={})),
            patch("routers.config.append_to_openclaw_config_list", AsyncMock()) as mock_append,
            _mock_billing("starter"),
        ):
            resp = client.patch(
                "/api/v1/config",
                json={"patch": {"channels": {"telegram": {"enabled": True}}}},
            )
        assert resp.status_code == 200
        mock_append.assert_not_called()
    finally:
        cleanup()
