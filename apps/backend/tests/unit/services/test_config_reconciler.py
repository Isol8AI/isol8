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
