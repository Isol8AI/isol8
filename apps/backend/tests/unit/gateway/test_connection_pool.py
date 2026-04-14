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
    ) as mock_update:
        await pool.record_activity("user_1")
        await pool.record_activity("user_2")

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
