"""Integration tests for the config reconciler against a real tmp filesystem
and real fcntl.lockf locking (no mocks around the lock/IO layer).

These catch bugs that unit mocks miss: lock semantics, atomic rename,
concurrent writer races.
"""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from core.containers.config import write_openclaw_config
from core.services.config_reconciler import ConfigReconciler


@pytest.mark.asyncio
async def test_reconciler_reverts_drift_end_to_end(tmp_path, monkeypatch):
    user = "user_e2e"
    udir = tmp_path / user
    udir.mkdir()
    cfg = udir / "openclaw.json"
    base = json.loads(write_openclaw_config(gateway_token="t", tier="free"))
    base["agents"]["defaults"]["model"]["primary"] = "amazon-bedrock/qwen.qwen3-vl-235b-a22b"
    base["channels"]["telegram"]["accounts"] = {"bot1": {"botToken": "x"}}
    cfg.write_text(json.dumps(base, indent=2))

    # Patch the module-level _efs_mount_path used inside _locked_rmw.
    monkeypatch.setattr("core.services.config_patcher._efs_mount_path", str(tmp_path))
    monkeypatch.setattr(
        "core.services.config_reconciler.settings.CONFIG_RECONCILER_MODE",
        "enforce",
        raising=False,
    )
    monkeypatch.setattr(
        "core.services.config_reconciler.container_repo.list_active_owners",
        AsyncMock(return_value=[user]),
    )
    monkeypatch.setattr(
        "core.services.config_reconciler.container_repo.get_reconciler_grace",
        AsyncMock(return_value=0),
    )
    monkeypatch.setattr(
        "core.services.config_reconciler.billing_repo.get_by_owner_id",
        AsyncMock(return_value={"plan_tier": "free"}),
    )

    r = ConfigReconciler(efs_mount=str(tmp_path), tick_interval=0.1)
    await r._tick()

    restored = json.loads(cfg.read_text())
    assert restored["agents"]["defaults"]["model"]["primary"] == "amazon-bedrock/minimax.minimax-m2.5"
    assert restored["channels"]["telegram"]["accounts"] == {}


@pytest.mark.asyncio
async def test_reconciler_serializes_with_config_patcher(tmp_path, monkeypatch):
    """Fire a reconciler tick and a config_patcher patch in parallel.
    The result must be a single valid JSON file (no interleaved writes)."""
    import json as _json
    from core.services import config_patcher

    user = "user_par"
    udir = tmp_path / user
    udir.mkdir()
    cfg = udir / "openclaw.json"
    base = _json.loads(write_openclaw_config(gateway_token="t", tier="free"))
    cfg.write_text(_json.dumps(base, indent=2))

    monkeypatch.setattr("core.services.config_patcher._efs_mount_path", str(tmp_path))
    monkeypatch.setattr(
        "core.services.config_reconciler.settings.CONFIG_RECONCILER_MODE",
        "enforce",
        raising=False,
    )
    monkeypatch.setattr(
        "core.services.config_reconciler.container_repo.list_active_owners",
        AsyncMock(return_value=[user]),
    )
    monkeypatch.setattr(
        "core.services.config_reconciler.container_repo.get_reconciler_grace",
        AsyncMock(return_value=0),
    )
    monkeypatch.setattr(
        "core.services.config_reconciler.billing_repo.get_by_owner_id",
        AsyncMock(return_value={"plan_tier": "free"}),
    )

    r = ConfigReconciler(efs_mount=str(tmp_path))
    await asyncio.gather(
        r._tick(),
        config_patcher.patch_openclaw_config(user, {"tools": {"web": {"fetch": {"enabled": False}}}}),
    )

    # File must still parse and contain both changes' non-conflicting pieces.
    result = _json.loads(cfg.read_text())
    assert result["tools"]["web"]["fetch"]["enabled"] is False
