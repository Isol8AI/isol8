"""Tests for PATCH /api/v1/config router."""

import os
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")

from core.auth import AuthContext  # noqa: E402


def _free_providers():
    from core.containers.config import _models_for_tier

    return {
        "amazon-bedrock": {
            "baseUrl": "https://bedrock-runtime.us-east-1.amazonaws.com",
            "api": "bedrock-converse-stream",
            "auth": "aws-sdk",
            "models": _models_for_tier("free"),
        },
    }


def _clean_base(tier: str) -> dict:
    """Return a policy-clean openclaw.json base for *tier* (for
    ``read_openclaw_config_from_efs`` mocks in tests that don't care about
    the base config — just that it passes the policy gate)."""
    from core.config import TIER_CONFIG
    from core.containers.config import _agent_models_for_tier, _models_for_tier

    primary = f"amazon-bedrock/{TIER_CONFIG[tier]['primary_model'].removeprefix('amazon-bedrock/')}"
    return {
        "models": {
            "providers": {
                "amazon-bedrock": {
                    "baseUrl": "https://bedrock-runtime.us-east-1.amazonaws.com",
                    "api": "bedrock-converse-stream",
                    "auth": "aws-sdk",
                    "models": _models_for_tier(tier),
                },
            },
        },
        "agents": {
            "defaults": {
                "model": {"primary": primary},
                "models": _agent_models_for_tier(tier, primary),
            },
        },
    }


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
        with (
            patch("routers.config.patch_openclaw_config", AsyncMock()) as mock_patch,
            patch(
                "routers.config.read_openclaw_config_from_efs",
                AsyncMock(return_value=_clean_base("starter")),
            ),
            _mock_billing("starter"),
        ):
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
        with (
            patch("routers.config.patch_openclaw_config", AsyncMock()) as mock_patch,
            patch(
                "routers.config.read_openclaw_config_from_efs",
                AsyncMock(return_value=_clean_base("pro")),
            ),
            _mock_billing("pro"),
        ):
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
        with (
            patch("routers.config.patch_openclaw_config", AsyncMock()) as mock_patch,
            patch(
                "routers.config.read_openclaw_config_from_efs",
                AsyncMock(return_value=_clean_base("pro")),
            ),
            _mock_billing("pro"),
        ):
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
        with (
            patch("routers.config.patch_openclaw_config", AsyncMock()) as mock_patch,
            patch(
                "routers.config.read_openclaw_config_from_efs",
                AsyncMock(
                    return_value={
                        "channels": {"telegram": {"enabled": True, "dmPolicy": "pairing"}},
                        "models": {"providers": _free_providers()},
                        "agents": {
                            "defaults": {
                                "model": {"primary": "amazon-bedrock/minimax.minimax-m2.5"},
                                "models": {"amazon-bedrock/minimax.minimax-m2.5": {"alias": "MiniMax M2.5"}},
                            }
                        },
                    }
                ),
            ),
            _mock_billing("free"),
        ):
            resp = client.patch(
                "/api/v1/config",
                json={"patch": {"channels": {"telegram": {"accounts": {"a": {"botToken": "x"}}}}}},
            )
        assert resp.status_code == 403
        detail = resp.json().get("detail", {})
        assert detail.get("code") == "policy_violation"
        assert "channels.accounts" in detail.get("fields", [])
        mock_patch.assert_not_called()
    finally:
        cleanup()


def test_patch_config_free_tier_non_channels_succeeds(client):
    cleanup = _patch_auth(_personal_auth())
    try:
        with (
            patch("routers.config.patch_openclaw_config", AsyncMock()) as mock_patch,
            patch(
                "routers.config.read_openclaw_config_from_efs",
                AsyncMock(return_value=_clean_base("free")),
            ),
            _mock_billing("free"),
        ):
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
        existing_cfg = _clean_base("pro")
        existing_cfg["channels"] = {
            "telegram": {
                "accounts": {
                    "main": {"botToken": "SHARED_TOKEN"},
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
        existing_cfg = _clean_base("pro")
        existing_cfg["channels"] = {
            "telegram": {
                "accounts": {
                    "main": {"botToken": "OLD_TOKEN"},
                },
            },
        }
        with (
            patch("routers.config.patch_openclaw_config", AsyncMock()) as mock_patch,
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


def test_patch_config_rejects_unauthorized_provider_any_tier(client):
    cleanup = _patch_auth(_personal_auth())
    try:
        with (
            patch("routers.config.patch_openclaw_config", AsyncMock()) as mock_patch,
            patch(
                "routers.config.read_openclaw_config_from_efs",
                AsyncMock(
                    return_value={
                        "models": {"providers": _free_providers()},
                        "agents": {
                            "defaults": {
                                "model": {"primary": "amazon-bedrock/minimax.minimax-m2.5"},
                                "models": {"amazon-bedrock/minimax.minimax-m2.5": {"alias": "MiniMax M2.5"}},
                            }
                        },
                    }
                ),
            ),
            _mock_billing("pro"),
        ):
            resp = client.patch(
                "/api/v1/config",
                json={"patch": {"models": {"providers": {"openai": {"api": "openai", "baseUrl": "x", "models": []}}}}},
            )
        assert resp.status_code == 403
        detail = resp.json().get("detail", {})
        assert detail.get("code") == "policy_violation"
        assert "models.providers" in detail.get("fields", [])
        mock_patch.assert_not_called()
    finally:
        cleanup()


def test_patch_config_accepts_non_locked_field_change(client):
    cleanup = _patch_auth(_personal_auth())
    try:
        with (
            patch("routers.config.patch_openclaw_config", AsyncMock()) as mock_patch,
            patch(
                "routers.config.read_openclaw_config_from_efs",
                AsyncMock(
                    return_value={
                        "models": {"providers": _free_providers()},
                        "agents": {
                            "defaults": {
                                "model": {"primary": "amazon-bedrock/minimax.minimax-m2.5"},
                                "models": {"amazon-bedrock/minimax.minimax-m2.5": {"alias": "MiniMax M2.5"}},
                            }
                        },
                    }
                ),
            ),
            _mock_billing("free"),
        ):
            resp = client.patch(
                "/api/v1/config",
                json={"patch": {"tools": {"web": {"search": {"enabled": False}}}}},
            )
        assert resp.status_code == 200
        mock_patch.assert_awaited_once()
    finally:
        cleanup()


def test_patch_config_missing_config_returns_404_not_403(client):
    """When openclaw.json doesn't exist yet (read returns None), we must NOT
    run policy evaluation against an empty {} (which would flag
    models.providers as violating the tier allowlist and return a misleading
    403 policy_violation). Instead the downstream patch must surface the real
    404 not-found error, so callers can distinguish "your patch violates
    policy" from "your config doesn't exist yet"."""
    from core.services.config_patcher import ConfigPatchError

    cleanup = _patch_auth(_personal_auth())
    try:
        with (
            patch(
                "routers.config.patch_openclaw_config",
                AsyncMock(side_effect=ConfigPatchError("Config not found for owner user_personal")),
            ) as mock_patch,
            patch(
                "routers.config.read_openclaw_config_from_efs",
                AsyncMock(return_value=None),
            ),
            _mock_billing("free"),
        ):
            resp = client.patch(
                "/api/v1/config",
                # This patch WOULD violate policy (unauthorized provider) if
                # policy evaluation ran against an empty current config.
                json={
                    "patch": {
                        "models": {
                            "providers": {
                                "openai": {
                                    "api": "openai",
                                    "baseUrl": "x",
                                    "models": [],
                                }
                            }
                        }
                    }
                },
            )
        assert resp.status_code == 404
        assert "Config not found" in resp.json().get("detail", "")
        # Downstream patch WAS called (i.e., we did not short-circuit with 403)
        mock_patch.assert_awaited_once()
    finally:
        cleanup()
