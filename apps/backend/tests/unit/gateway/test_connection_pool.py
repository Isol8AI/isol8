"""Tests for GatewayConnectionPool public methods."""

import os

import pytest

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")


@pytest.mark.asyncio
async def test_close_user_no_longer_references_last_activity():
    """Regression: close_user used to pop _last_activity, now that dict is
    gone. Should run cleanly for a user it's never seen — no AttributeError /
    KeyError from the removed code path."""
    from core.gateway.connection_pool import GatewayConnectionPool

    pool = GatewayConnectionPool(management_api=None)
    # Should not raise
    await pool.close_user("user_never_connected")
