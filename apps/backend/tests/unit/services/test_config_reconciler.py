"""Tests for ConfigReconciler lifecycle + tick logic."""

import asyncio

import pytest


@pytest.mark.asyncio
async def test_reconciler_run_forever_exits_when_stop_set():
    from core.services.config_reconciler import ConfigReconciler

    r = ConfigReconciler(efs_mount="/tmp/does-not-exist-for-test")
    task = asyncio.create_task(r.run_forever())

    # Give it a moment to enter the loop, then stop it.
    await asyncio.sleep(0.05)
    r.stop()

    # It should exit within one tick interval + a small margin.
    await asyncio.wait_for(task, timeout=2.0)


@pytest.mark.asyncio
async def test_reconciler_swallows_tick_exceptions(monkeypatch, caplog):
    """A raised exception inside _tick must not kill run_forever."""
    from core.services.config_reconciler import ConfigReconciler

    r = ConfigReconciler(efs_mount="/tmp")

    call_count = 0

    async def boom():
        nonlocal call_count
        call_count += 1
        raise RuntimeError("synthetic tick failure")

    monkeypatch.setattr(r, "_tick", boom)

    task = asyncio.create_task(r.run_forever())
    await asyncio.sleep(2.2)  # enough for multiple tick attempts
    r.stop()
    await asyncio.wait_for(task, timeout=2.0)
    assert call_count >= 2  # loop kept going despite exceptions


@pytest.mark.asyncio
async def test_tick_skips_user_when_mtime_unchanged(tmp_path, monkeypatch):
    from core.services.config_reconciler import ConfigReconciler

    user_dir = tmp_path / "user_A"
    user_dir.mkdir()
    cfg = user_dir / "openclaw.json"
    cfg.write_text('{"models":{"providers":{}}}')

    r = ConfigReconciler(efs_mount=str(tmp_path))

    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "core.services.config_reconciler.container_repo.list_active_owners",
        AsyncMock(return_value=["user_A"]),
    )

    read_count = 0
    original_open = open

    def tracked_open(path, *a, **kw):
        nonlocal read_count
        if str(path).endswith("openclaw.json"):
            read_count += 1
        return original_open(path, *a, **kw)

    monkeypatch.setattr("builtins.open", tracked_open)

    # First tick — mtime unseen, should read.
    await r._tick()
    first_reads = read_count

    # Second tick — mtime unchanged, should skip read.
    await r._tick()
    assert read_count == first_reads, "second tick must not re-read unchanged file"


@pytest.mark.asyncio
async def test_tick_handles_missing_config_file(tmp_path, monkeypatch):
    from core.services.config_reconciler import ConfigReconciler
    from unittest.mock import AsyncMock

    r = ConfigReconciler(efs_mount=str(tmp_path))
    monkeypatch.setattr(
        "core.services.config_reconciler.container_repo.list_active_owners",
        AsyncMock(return_value=["ghost_user"]),
    )

    # Should not raise.
    await r._tick()


@pytest.mark.asyncio
async def test_tick_reverts_drift_in_enforce_mode(tmp_path, monkeypatch):
    import json
    from unittest.mock import AsyncMock

    from core.containers.config import write_openclaw_config
    from core.services.config_reconciler import ConfigReconciler

    user = "user_drift"
    udir = tmp_path / user
    udir.mkdir()
    cfg_path = udir / "openclaw.json"
    # Start with a clean free-tier config, then mutate it in-file.
    base = json.loads(write_openclaw_config(gateway_token="t", tier="free"))
    base["agents"]["defaults"]["model"]["primary"] = "amazon-bedrock/qwen.qwen3-vl-235b-a22b"
    cfg_path.write_text(json.dumps(base, indent=2))

    r = ConfigReconciler(efs_mount=str(tmp_path))
    monkeypatch.setattr("core.services.config_reconciler.settings.CONFIG_RECONCILER_MODE", "enforce", raising=False)
    monkeypatch.setattr("core.services.config_patcher._efs_mount_path", str(tmp_path))
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

    await r._tick()

    on_disk = json.loads(cfg_path.read_text())
    assert on_disk["agents"]["defaults"]["model"]["primary"] == "amazon-bedrock/minimax.minimax-m2.5"


@pytest.mark.asyncio
async def test_tick_report_mode_does_not_write(tmp_path, monkeypatch):
    import json
    from unittest.mock import AsyncMock

    from core.containers.config import write_openclaw_config
    from core.services.config_reconciler import ConfigReconciler

    user = "user_report"
    udir = tmp_path / user
    udir.mkdir()
    cfg_path = udir / "openclaw.json"
    base = json.loads(write_openclaw_config(gateway_token="t", tier="free"))
    base["agents"]["defaults"]["model"]["primary"] = "amazon-bedrock/qwen.qwen3-vl-235b-a22b"
    cfg_path.write_text(json.dumps(base, indent=2))
    drift_mtime = cfg_path.stat().st_mtime

    r = ConfigReconciler(efs_mount=str(tmp_path))
    monkeypatch.setattr("core.services.config_reconciler.settings.CONFIG_RECONCILER_MODE", "report", raising=False)
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

    await r._tick()

    # mtime unchanged → no write happened
    assert cfg_path.stat().st_mtime == drift_mtime


@pytest.mark.asyncio
async def test_tick_off_mode_no_op(tmp_path, monkeypatch):
    """CONFIG_RECONCILER_MODE=off must short-circuit _tick before any
    DDB / EFS / billing work."""
    from unittest.mock import AsyncMock

    from core.services.config_reconciler import ConfigReconciler

    r = ConfigReconciler(efs_mount=str(tmp_path))
    monkeypatch.setattr(
        "core.services.config_reconciler.settings.CONFIG_RECONCILER_MODE",
        "off",
        raising=False,
    )

    list_owners = AsyncMock(return_value=["user_off"])
    get_grace = AsyncMock(return_value=0)
    get_billing = AsyncMock(return_value={"plan_tier": "free"})
    monkeypatch.setattr(
        "core.services.config_reconciler.container_repo.list_active_owners",
        list_owners,
    )
    monkeypatch.setattr(
        "core.services.config_reconciler.container_repo.get_reconciler_grace",
        get_grace,
    )
    monkeypatch.setattr(
        "core.services.config_reconciler.billing_repo.get_by_owner_id",
        get_billing,
    )

    await r._tick()

    # off mode must short-circuit before any IO.
    list_owners.assert_not_called()
    get_grace.assert_not_called()
    get_billing.assert_not_called()


@pytest.mark.asyncio
async def test_tick_unknown_mode_warns_and_no_op(tmp_path, monkeypatch, caplog):
    """An unknown CONFIG_RECONCILER_MODE value must log a warning and
    leave drift on disk (behave as ``off`` at the per-owner level)."""
    import json
    import logging
    from unittest.mock import AsyncMock

    from core.containers.config import write_openclaw_config
    from core.services.config_reconciler import ConfigReconciler

    user = "user_unknown_mode"
    udir = tmp_path / user
    udir.mkdir()
    cfg_path = udir / "openclaw.json"
    base = json.loads(write_openclaw_config(gateway_token="t", tier="free"))
    base["agents"]["defaults"]["model"]["primary"] = "amazon-bedrock/qwen.qwen3-vl-235b-a22b"
    cfg_path.write_text(json.dumps(base, indent=2))
    pre_mtime = cfg_path.stat().st_mtime

    r = ConfigReconciler(efs_mount=str(tmp_path))
    monkeypatch.setattr(
        "core.services.config_reconciler.settings.CONFIG_RECONCILER_MODE",
        "bogus",
        raising=False,
    )
    monkeypatch.setattr(
        "core.services.config_reconciler.container_repo.get_reconciler_grace",
        AsyncMock(return_value=0),
    )
    monkeypatch.setattr(
        "core.services.config_reconciler.billing_repo.get_by_owner_id",
        AsyncMock(return_value={"plan_tier": "free"}),
    )

    with caplog.at_level(logging.WARNING):
        await r._check_one(user)

    # No write happened (drift stays on disk).
    assert cfg_path.stat().st_mtime == pre_mtime
    on_disk = json.loads(cfg_path.read_text())
    assert on_disk["agents"]["defaults"]["model"]["primary"] == "amazon-bedrock/qwen.qwen3-vl-235b-a22b"
    # Warning was logged.
    assert any("unknown CONFIG_RECONCILER_MODE" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_tick_re_evaluates_when_tier_changes_even_without_mtime_change(tmp_path, monkeypatch):
    """Plan downgrade (paid→free) with no file edit: once the tier-cache TTL
    lapses and the tier resolves to the new value, the reconciler must
    re-read the config and revert now-illegal pro-only fields."""
    import json
    from unittest.mock import AsyncMock

    from core.containers.config import write_openclaw_config
    from core.services.config_reconciler import ConfigReconciler

    user = "user_tier_change"
    udir = tmp_path / user
    udir.mkdir()
    cfg_path = udir / "openclaw.json"
    # Write a valid pro config (pro-tier primary model).
    base = json.loads(write_openclaw_config(gateway_token="t", tier="pro"))
    cfg_path.write_text(json.dumps(base, indent=2))

    # Use tier_cache_ttl=0 so each _resolve_tier call hits the mocked billing.
    r = ConfigReconciler(efs_mount=str(tmp_path), tier_cache_ttl=0.0)
    monkeypatch.setattr(
        "core.services.config_reconciler.settings.CONFIG_RECONCILER_MODE",
        "enforce",
        raising=False,
    )
    monkeypatch.setattr("core.services.config_patcher._efs_mount_path", str(tmp_path))
    monkeypatch.setattr(
        "core.services.config_reconciler.container_repo.list_active_owners",
        AsyncMock(return_value=[user]),
    )
    monkeypatch.setattr(
        "core.services.config_reconciler.container_repo.get_reconciler_grace",
        AsyncMock(return_value=0),
    )

    # Mutable tier to flip between ticks without touching the file.
    current_tier = {"value": "pro"}
    monkeypatch.setattr(
        "core.services.config_reconciler.billing_repo.get_by_owner_id",
        AsyncMock(side_effect=lambda _oid: {"plan_tier": current_tier["value"]}),
    )

    open_count = 0
    original_open = open

    def tracked_open(path, *a, **kw):
        nonlocal open_count
        if str(path).endswith("openclaw.json"):
            open_count += 1
        return original_open(path, *a, **kw)

    monkeypatch.setattr("builtins.open", tracked_open)

    # First tick as pro: config is compliant. The file IS opened for evaluation.
    await r._tick()
    opens_after_pro = open_count
    assert opens_after_pro >= 1, "first tick must open the file to evaluate it"

    # Flip to free without touching the file.
    current_tier["value"] = "free"

    await r._tick()

    # We MUST have re-opened the file on the second tick (tier changed).
    assert open_count > opens_after_pro, "tier change must trigger re-read even with unchanged mtime"

    # And now the pro-only primary must have been reverted to the free default.
    on_disk = json.loads(cfg_path.read_text())
    assert on_disk["agents"]["defaults"]["model"]["primary"] == "amazon-bedrock/minimax.minimax-m2.5"


@pytest.mark.asyncio
async def test_tick_skips_when_both_mtime_and_tier_unchanged(tmp_path, monkeypatch):
    """Two ticks in a row with identical mtime + identical tier must only
    read the config file once."""
    from unittest.mock import AsyncMock

    from core.services.config_reconciler import ConfigReconciler

    user = "user_stable"
    udir = tmp_path / user
    udir.mkdir()
    cfg = udir / "openclaw.json"
    cfg.write_text('{"models":{"providers":{}}}')

    r = ConfigReconciler(efs_mount=str(tmp_path), tier_cache_ttl=0.0)
    monkeypatch.setattr(
        "core.services.config_reconciler.settings.CONFIG_RECONCILER_MODE",
        "report",
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

    read_count = 0
    original_open = open

    def tracked_open(path, *a, **kw):
        nonlocal read_count
        if str(path).endswith("openclaw.json"):
            read_count += 1
        return original_open(path, *a, **kw)

    monkeypatch.setattr("builtins.open", tracked_open)

    await r._tick()
    first_reads = read_count
    await r._tick()
    assert read_count == first_reads, "second tick with same mtime + same tier must not re-read config"


@pytest.mark.asyncio
async def test_tick_honors_grace_window(tmp_path, monkeypatch):
    import json
    import time
    from unittest.mock import AsyncMock

    from core.containers.config import write_openclaw_config
    from core.services.config_reconciler import ConfigReconciler

    user = "user_grace"
    udir = tmp_path / user
    udir.mkdir()
    cfg_path = udir / "openclaw.json"
    base = json.loads(write_openclaw_config(gateway_token="t", tier="free"))
    base["agents"]["defaults"]["model"]["primary"] = "amazon-bedrock/qwen.qwen3-vl-235b-a22b"
    cfg_path.write_text(json.dumps(base, indent=2))
    pre_mtime = cfg_path.stat().st_mtime

    r = ConfigReconciler(efs_mount=str(tmp_path))
    monkeypatch.setattr("core.services.config_reconciler.settings.CONFIG_RECONCILER_MODE", "enforce", raising=False)
    monkeypatch.setattr(
        "core.services.config_reconciler.container_repo.list_active_owners",
        AsyncMock(return_value=[user]),
    )
    # Grace is in the future → skip revert.
    monkeypatch.setattr(
        "core.services.config_reconciler.container_repo.get_reconciler_grace",
        AsyncMock(return_value=int(time.time()) + 30),
    )
    monkeypatch.setattr(
        "core.services.config_reconciler.billing_repo.get_by_owner_id",
        AsyncMock(return_value={"plan_tier": "free"}),
    )

    await r._tick()
    assert cfg_path.stat().st_mtime == pre_mtime
