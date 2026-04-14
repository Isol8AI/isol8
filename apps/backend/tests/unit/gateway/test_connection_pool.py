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
async def test_record_activity_releases_cooldown_on_noop_write():
    """Cold-start regression: when update_last_active returns False (row still
    status=stopped before start_user_service has flipped it), the cooldown
    must be released so the next ping retries immediately. Otherwise the
    reaper could see a null last_active_at on the next cycle and stop an
    actively-used container.
    """
    from core.gateway.connection_pool import GatewayConnectionPool, _LAST_DDB_WRITE

    _LAST_DDB_WRITE.clear()
    pool = GatewayConnectionPool(management_api=None)

    with patch(
        "core.repositories.container_repo.update_last_active",
        new_callable=AsyncMock,
        return_value=False,
    ) as mock_update:
        await pool.record_activity("user_1")

    mock_update.assert_awaited_once()
    # Cooldown must NOT be set; next ping should go through.
    assert "user_1" not in _LAST_DDB_WRITE


@pytest.mark.asyncio
async def test_record_activity_retries_immediately_after_noop_write():
    """Companion to the above: after a no-op write, a second ping in the
    same instant should fire another write — cooldown was released, so no
    30s lockout."""
    from core.gateway.connection_pool import GatewayConnectionPool, _LAST_DDB_WRITE

    _LAST_DDB_WRITE.clear()
    pool = GatewayConnectionPool(management_api=None)

    # First call: row is stopped, returns False. Second call: row is now
    # running, returns True. Both should reach update_last_active.
    with patch(
        "core.repositories.container_repo.update_last_active",
        new_callable=AsyncMock,
        side_effect=[False, True],
    ) as mock_update:
        await pool.record_activity("user_1")
        await pool.record_activity("user_1")

    assert mock_update.await_count == 2


@pytest.mark.asyncio
async def test_close_user_no_longer_references_last_activity():
    """Regression for Task 4: close_user used to pop _last_activity, now that
    dict is gone. This test ensures close_user runs cleanly for a user it's
    never seen — no AttributeError / KeyError from the removed code path."""
    from core.gateway.connection_pool import GatewayConnectionPool

    pool = GatewayConnectionPool(management_api=None)
    # Should not raise
    await pool.close_user("user_never_connected")
