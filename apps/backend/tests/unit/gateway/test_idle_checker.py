"""Tests for the free-tier scale-to-zero reaper."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


@pytest.mark.asyncio
async def test_reaps_disconnected_idle_free_user():
    """Regression for the core bug: a free user with no open WS gets reaped
    anyway because the reaper walks DDB, not self._connections."""
    from core.gateway.connection_pool import GatewayConnectionPool

    old_ts = _iso(datetime.now(timezone.utc) - timedelta(minutes=6))
    pool = GatewayConnectionPool(management_api=None)

    with (
        patch(
            "core.repositories.container_repo.get_by_status",
            new_callable=AsyncMock,
            return_value=[{"owner_id": "user_free", "status": "running", "last_active_at": old_ts}],
        ),
        patch(
            "core.repositories.billing_repo.get_by_owner_id",
            new_callable=AsyncMock,
            return_value={"owner_id": "user_free", "plan_tier": "free"},
        ),
        patch("core.containers.get_ecs_manager") as mock_get_ecs,
        patch(
            "core.repositories.container_repo.mark_stopped_if_running",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_mark_stopped,
    ):
        ecs = mock_get_ecs.return_value
        ecs.stop_user_service = AsyncMock()

        stopped = await pool._reap_once()

        ecs.stop_user_service.assert_awaited_once_with("user_free")
        mock_mark_stopped.assert_awaited_once_with("user_free")
        assert stopped == ["user_free"]


@pytest.mark.asyncio
async def test_treats_orphan_as_free():
    from core.gateway.connection_pool import GatewayConnectionPool

    old_ts = _iso(datetime.now(timezone.utc) - timedelta(minutes=10))
    pool = GatewayConnectionPool(management_api=None)

    with (
        patch(
            "core.repositories.container_repo.get_by_status",
            new_callable=AsyncMock,
            return_value=[{"owner_id": "user_orphan", "status": "running", "last_active_at": old_ts}],
        ),
        patch(
            "core.repositories.billing_repo.get_by_owner_id",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("core.containers.get_ecs_manager") as mock_get_ecs,
        patch(
            "core.repositories.container_repo.mark_stopped_if_running",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        ecs = mock_get_ecs.return_value
        ecs.stop_user_service = AsyncMock()

        stopped = await pool._reap_once()

        ecs.stop_user_service.assert_awaited_once_with("user_orphan")
        assert stopped == ["user_orphan"]


@pytest.mark.asyncio
async def test_skips_paid_tier():
    from core.gateway.connection_pool import GatewayConnectionPool

    old_ts = _iso(datetime.now(timezone.utc) - timedelta(minutes=60))
    pool = GatewayConnectionPool(management_api=None)

    with (
        patch(
            "core.repositories.container_repo.get_by_status",
            new_callable=AsyncMock,
            return_value=[{"owner_id": "user_paid", "status": "running", "last_active_at": old_ts}],
        ),
        patch(
            "core.repositories.billing_repo.get_by_owner_id",
            new_callable=AsyncMock,
            return_value={"owner_id": "user_paid", "plan_tier": "starter"},
        ),
        patch("core.containers.get_ecs_manager") as mock_get_ecs,
    ):
        ecs = mock_get_ecs.return_value
        ecs.stop_user_service = AsyncMock()

        stopped = await pool._reap_once()

        ecs.stop_user_service.assert_not_awaited()
        assert stopped == []


@pytest.mark.asyncio
async def test_skips_not_yet_idle():
    from core.gateway.connection_pool import GatewayConnectionPool

    recent_ts = _iso(datetime.now(timezone.utc) - timedelta(seconds=120))
    pool = GatewayConnectionPool(management_api=None)

    with (
        patch(
            "core.repositories.container_repo.get_by_status",
            new_callable=AsyncMock,
            return_value=[{"owner_id": "user_free", "status": "running", "last_active_at": recent_ts}],
        ),
        patch(
            "core.repositories.billing_repo.get_by_owner_id",
            new_callable=AsyncMock,
            return_value={"owner_id": "user_free", "plan_tier": "free"},
        ),
        patch("core.containers.get_ecs_manager") as mock_get_ecs,
    ):
        ecs = mock_get_ecs.return_value
        ecs.stop_user_service = AsyncMock()

        stopped = await pool._reap_once()

        ecs.stop_user_service.assert_not_awaited()
        assert stopped == []


@pytest.mark.asyncio
async def test_reaps_row_with_null_last_active_at():
    """Deploy-day path: rows from before this change have no last_active_at.
    They must be treated as very old and reaped on first cycle."""
    from core.gateway.connection_pool import GatewayConnectionPool

    pool = GatewayConnectionPool(management_api=None)

    with (
        patch(
            "core.repositories.container_repo.get_by_status",
            new_callable=AsyncMock,
            return_value=[{"owner_id": "user_stale", "status": "running"}],
        ),
        patch(
            "core.repositories.billing_repo.get_by_owner_id",
            new_callable=AsyncMock,
            return_value={"owner_id": "user_stale", "plan_tier": "free"},
        ),
        patch("core.containers.get_ecs_manager") as mock_get_ecs,
        patch(
            "core.repositories.container_repo.mark_stopped_if_running",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        ecs = mock_get_ecs.return_value
        ecs.stop_user_service = AsyncMock()

        stopped = await pool._reap_once()

        ecs.stop_user_service.assert_awaited_once_with("user_stale")
        assert stopped == ["user_stale"]


@pytest.mark.asyncio
async def test_honors_scale_to_zero_flag_not_string_literal():
    """The reaper reads TIER_CONFIG['<tier>']['scale_to_zero'], not a hard 'free' string.
    Mutating the flag changes behavior."""
    from core.gateway.connection_pool import GatewayConnectionPool

    old_ts = _iso(datetime.now(timezone.utc) - timedelta(minutes=30))
    pool = GatewayConnectionPool(management_api=None)

    with (
        patch(
            "core.gateway.connection_pool.TIER_CONFIG",
            {"trial": {"scale_to_zero": True}, "starter": {"scale_to_zero": False}},
        ),
        patch(
            "core.repositories.container_repo.get_by_status",
            new_callable=AsyncMock,
            return_value=[{"owner_id": "user_trial", "status": "running", "last_active_at": old_ts}],
        ),
        patch(
            "core.repositories.billing_repo.get_by_owner_id",
            new_callable=AsyncMock,
            return_value={"owner_id": "user_trial", "plan_tier": "trial"},
        ),
        patch("core.containers.get_ecs_manager") as mock_get_ecs,
        patch(
            "core.repositories.container_repo.mark_stopped_if_running",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        ecs = mock_get_ecs.return_value
        ecs.stop_user_service = AsyncMock()

        stopped = await pool._reap_once()

        ecs.stop_user_service.assert_awaited_once_with("user_trial")
        assert stopped == ["user_trial"]


@pytest.mark.asyncio
async def test_reaper_survives_billing_lookup_failure():
    from core.gateway.connection_pool import GatewayConnectionPool

    old_ts = _iso(datetime.now(timezone.utc) - timedelta(minutes=30))
    pool = GatewayConnectionPool(management_api=None)

    with (
        patch(
            "core.repositories.container_repo.get_by_status",
            new_callable=AsyncMock,
            return_value=[
                {"owner_id": "user_a", "status": "running", "last_active_at": old_ts},
                {"owner_id": "user_b", "status": "running", "last_active_at": old_ts},
            ],
        ),
        patch(
            "core.repositories.billing_repo.get_by_owner_id",
            new_callable=AsyncMock,
            side_effect=[RuntimeError("ddb blip"), {"owner_id": "user_b", "plan_tier": "free"}],
        ),
        patch("core.containers.get_ecs_manager") as mock_get_ecs,
        patch(
            "core.repositories.container_repo.mark_stopped_if_running",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        ecs = mock_get_ecs.return_value
        ecs.stop_user_service = AsyncMock()

        stopped = await pool._reap_once()

        # user_a was skipped due to billing failure; user_b still reaped
        assert stopped == ["user_b"]
