"""Tests for backend lifespan startup/shutdown wiring."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_safe_idle_checker_emits_crash_metric_on_exception():
    """When the reaper (idle checker) raises, we MUST emit gateway.idle_checker.crash.

    Task 9's CloudWatch alarm hardcodes this exact metric name — any deviation
    means the alarm never fires when the reaper dies silently.
    """
    from main import _safe_idle_checker

    failing_pool = MagicMock()
    failing_pool.run_idle_checker = AsyncMock(side_effect=RuntimeError("boom"))

    with (
        patch("main.get_gateway_pool", return_value=failing_pool),
        patch("main.put_metric") as mock_put_metric,
    ):
        await _safe_idle_checker()

    mock_put_metric.assert_any_call("gateway.idle_checker.crash")
