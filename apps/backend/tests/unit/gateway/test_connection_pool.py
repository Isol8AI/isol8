"""Tests for GatewayConnectionPool public methods."""

import os
import time
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")


@pytest.mark.asyncio
async def test_record_activity_writes_ddb_on_first_call():
    from core.gateway.connection_pool import GatewayConnectionPool, _LAST_DDB_WRITE

    _LAST_DDB_WRITE.clear()
    pool = GatewayConnectionPool(management_api=None)

    with patch(
        "core.repositories.container_repo.update_last_active",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_update:
        await pool.record_activity("user_1")

    mock_update.assert_awaited_once()
    assert mock_update.await_args.args[0] == "user_1"
    # Second arg is an ISO-8601 UTC string
    assert "T" in mock_update.await_args.args[1]


@pytest.mark.asyncio
async def test_record_activity_coalesces_within_cooldown():
    from core.gateway.connection_pool import GatewayConnectionPool, _LAST_DDB_WRITE

    _LAST_DDB_WRITE.clear()
    pool = GatewayConnectionPool(management_api=None)

    with patch(
        "core.repositories.container_repo.update_last_active",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_update:
        await pool.record_activity("user_1")
        await pool.record_activity("user_1")
        await pool.record_activity("user_1")

    assert mock_update.await_count == 1


@pytest.mark.asyncio
async def test_record_activity_writes_again_after_cooldown():
    from core.gateway.connection_pool import GatewayConnectionPool, _LAST_DDB_WRITE

    _LAST_DDB_WRITE.clear()
    pool = GatewayConnectionPool(management_api=None)

    with patch(
        "core.repositories.container_repo.update_last_active",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_update:
        await pool.record_activity("user_1")
        # Simulate 31s elapsed by directly adjusting the coalesce map
        _LAST_DDB_WRITE["user_1"] = time.time() - 31.0
        await pool.record_activity("user_1")

    assert mock_update.await_count == 2


@pytest.mark.asyncio
async def test_record_activity_different_users_not_coalesced():
    from core.gateway.connection_pool import GatewayConnectionPool, _LAST_DDB_WRITE

    _LAST_DDB_WRITE.clear()
    pool = GatewayConnectionPool(management_api=None)

    with patch(
        "core.repositories.container_repo.update_last_active",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_update:
        await pool.record_activity("user_1")
        await pool.record_activity("user_2")

    assert mock_update.await_count == 2


@pytest.mark.asyncio
async def test_record_activity_backdates_cooldown_on_noop_write():
    """When update_last_active returns False (cold-start row=stopped, or
    missing row, or attacker pinging their own stopped container), the
    cooldown is BACKDATED to allow retry in ~_DDB_WRITE_RETRY_FLOOR seconds
    — not popped, not held the full 30s. Bounds DDB write rate during
    stopped-container windows.
    """
    from core.gateway.connection_pool import (
        _DDB_WRITE_COOLDOWN,
        _DDB_WRITE_RETRY_FLOOR,
        _LAST_DDB_WRITE,
        GatewayConnectionPool,
    )

    _LAST_DDB_WRITE.clear()
    pool = GatewayConnectionPool(management_api=None)

    with patch(
        "core.repositories.container_repo.update_last_active",
        new_callable=AsyncMock,
        return_value=False,
    ) as mock_update:
        before = time.time()
        await pool.record_activity("user_1")
        after = time.time()

    mock_update.assert_awaited_once()
    # Cooldown stamp should be back-dated to ≈ now - (cooldown - retry_floor),
    # i.e. the next allowed retry is exactly _DDB_WRITE_RETRY_FLOOR away.
    stamp = _LAST_DDB_WRITE["user_1"]
    expected_min = before - (_DDB_WRITE_COOLDOWN - _DDB_WRITE_RETRY_FLOOR)
    expected_max = after - (_DDB_WRITE_COOLDOWN - _DDB_WRITE_RETRY_FLOOR)
    assert expected_min <= stamp <= expected_max


@pytest.mark.asyncio
async def test_record_activity_retry_floor_gates_back_to_back_noop_writes():
    """Attack scenario: an authenticated user floods user_active against
    their own stopped container. Each ping would hit DDB on a conditional
    UpdateItem (which fails but still bills WCU). The retry floor caps this
    at one DDB call per _DDB_WRITE_RETRY_FLOOR seconds."""
    from core.gateway.connection_pool import GatewayConnectionPool, _LAST_DDB_WRITE

    _LAST_DDB_WRITE.clear()
    pool = GatewayConnectionPool(management_api=None)

    with patch(
        "core.repositories.container_repo.update_last_active",
        new_callable=AsyncMock,
        return_value=False,
    ) as mock_update:
        # 5 back-to-back pings (no time passes). Only the first should reach
        # DDB; the next 4 are gated by the backdated cooldown.
        for _ in range(5):
            await pool.record_activity("user_1")

    assert mock_update.await_count == 1


@pytest.mark.asyncio
async def test_record_activity_retries_after_retry_floor_elapses():
    """After ≥_DDB_WRITE_RETRY_FLOOR seconds have passed since a no-op,
    the next ping is allowed through. Confirms the floor is a *gate*, not
    a permanent lockout."""
    from core.gateway.connection_pool import (
        _DDB_WRITE_RETRY_FLOOR,
        _LAST_DDB_WRITE,
        GatewayConnectionPool,
    )

    _LAST_DDB_WRITE.clear()
    pool = GatewayConnectionPool(management_api=None)

    with patch(
        "core.repositories.container_repo.update_last_active",
        new_callable=AsyncMock,
        return_value=False,
    ) as mock_update:
        await pool.record_activity("user_1")
        # Roll the stamp back by retry-floor + 1s to simulate elapsed time.
        _LAST_DDB_WRITE["user_1"] -= _DDB_WRITE_RETRY_FLOOR + 1
        await pool.record_activity("user_1")

    assert mock_update.await_count == 2


@pytest.mark.asyncio
async def test_record_activity_retry_floor_also_gates_after_ddb_exception():
    """Symmetric to the no-op case: a DDB exception backdates the cooldown
    too. Prevents DDB outages from amplifying into a write storm once the
    service comes back up."""
    from core.gateway.connection_pool import (
        _DDB_WRITE_COOLDOWN,
        _DDB_WRITE_RETRY_FLOOR,
        _LAST_DDB_WRITE,
        GatewayConnectionPool,
    )

    _LAST_DDB_WRITE.clear()
    pool = GatewayConnectionPool(management_api=None)

    with patch(
        "core.repositories.container_repo.update_last_active",
        new_callable=AsyncMock,
        side_effect=RuntimeError("ddb blip"),
    ) as mock_update:
        before = time.time()
        await pool.record_activity("user_1")
        after = time.time()

    mock_update.assert_awaited_once()
    stamp = _LAST_DDB_WRITE["user_1"]
    expected_min = before - (_DDB_WRITE_COOLDOWN - _DDB_WRITE_RETRY_FLOOR)
    expected_max = after - (_DDB_WRITE_COOLDOWN - _DDB_WRITE_RETRY_FLOOR)
    assert expected_min <= stamp <= expected_max


@pytest.mark.asyncio
async def test_record_activity_retry_backdate_uses_post_await_time():
    """Codex P2 regression: the retry-floor stamp must be computed from
    time AFTER the DDB await, not before. Otherwise a slow update_last_active
    call (e.g. partial DDB outage) consumes the entire 30s cooldown by the
    time we get to the backdate line, and the next ping is admitted
    immediately — the opposite of the intended bound."""
    from core.gateway.connection_pool import (
        _DDB_WRITE_COOLDOWN,
        _DDB_WRITE_RETRY_FLOOR,
        _LAST_DDB_WRITE,
        GatewayConnectionPool,
    )

    _LAST_DDB_WRITE.clear()
    pool = GatewayConnectionPool(management_api=None)

    # Two time.time readings: 100.0 inside the entry-gate, then 105.0 inside
    # the post-await backdate (simulating a 5-second slow DDB call without
    # an actual sleep).
    times = iter([100.0, 105.0])

    with (
        patch(
            "core.repositories.container_repo.update_last_active",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "core.gateway.connection_pool.time.time",
            side_effect=lambda: next(times),
        ),
        # Suppress put_metric so its internal time.time() call doesn't consume
        # values from our `times` iterator. We're testing the backdate stamp,
        # not metric emission (covered separately).
        patch("core.gateway.connection_pool.put_metric"),
    ):
        await pool.record_activity("user_1")

    # Buggy version would stamp at 100.0 - 28 = 72.0 (pre-await `now`).
    # Fixed version stamps at 105.0 - 28 = 77.0 (post-await fresh time).
    expected = 105.0 - (_DDB_WRITE_COOLDOWN - _DDB_WRITE_RETRY_FLOOR)
    assert _LAST_DDB_WRITE["user_1"] == pytest.approx(expected)


@pytest.mark.asyncio
async def test_record_activity_emits_outcome_metric_on_success():
    """Observability: each record_activity call emits a count metric tagged
    with outcome=success / noop / error so we can graph the breakdown."""
    from core.gateway.connection_pool import GatewayConnectionPool, _LAST_DDB_WRITE

    _LAST_DDB_WRITE.clear()
    pool = GatewayConnectionPool(management_api=None)

    with (
        patch(
            "core.repositories.container_repo.update_last_active",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch("core.gateway.connection_pool.put_metric") as mock_put_metric,
    ):
        await pool.record_activity("user_1")

    outcomes = [
        c.kwargs.get("dimensions", {}).get("outcome")
        for c in mock_put_metric.call_args_list
        if c.args and c.args[0] == "gateway.record_activity.count"
    ]
    assert outcomes == ["success"]


@pytest.mark.asyncio
async def test_record_activity_emits_outcome_metric_on_noop():
    from core.gateway.connection_pool import GatewayConnectionPool, _LAST_DDB_WRITE

    _LAST_DDB_WRITE.clear()
    pool = GatewayConnectionPool(management_api=None)

    with (
        patch(
            "core.repositories.container_repo.update_last_active",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch("core.gateway.connection_pool.put_metric") as mock_put_metric,
    ):
        await pool.record_activity("user_1")

    outcomes = [
        c.kwargs.get("dimensions", {}).get("outcome")
        for c in mock_put_metric.call_args_list
        if c.args and c.args[0] == "gateway.record_activity.count"
    ]
    assert outcomes == ["noop"]


@pytest.mark.asyncio
async def test_record_activity_emits_outcome_metric_on_error():
    from core.gateway.connection_pool import GatewayConnectionPool, _LAST_DDB_WRITE

    _LAST_DDB_WRITE.clear()
    pool = GatewayConnectionPool(management_api=None)

    with (
        patch(
            "core.repositories.container_repo.update_last_active",
            new_callable=AsyncMock,
            side_effect=RuntimeError("ddb blip"),
        ),
        patch("core.gateway.connection_pool.put_metric") as mock_put_metric,
    ):
        await pool.record_activity("user_1")

    outcomes = [
        c.kwargs.get("dimensions", {}).get("outcome")
        for c in mock_put_metric.call_args_list
        if c.args and c.args[0] == "gateway.record_activity.count"
    ]
    assert outcomes == ["error"]


@pytest.mark.asyncio
async def test_close_user_no_longer_references_last_activity():
    """Regression for Task 4: close_user used to pop _last_activity, now that
    dict is gone. This test ensures close_user runs cleanly for a user it's
    never seen — no AttributeError / KeyError from the removed code path."""
    from core.gateway.connection_pool import GatewayConnectionPool

    pool = GatewayConnectionPool(management_api=None)
    # Should not raise
    await pool.close_user("user_never_connected")
