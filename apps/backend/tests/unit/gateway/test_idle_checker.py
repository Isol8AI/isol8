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
async def test_does_not_reap_fresh_running_container_with_no_last_active_at():
    """A container that just transitioned provisioning→running has no
    last_active_at yet (no chat traffic has flowed). The reaper must fall
    back to updated_at (or created_at) and grant the row its full 5-minute
    grace window from the moment it became running. Otherwise free-tier
    users get their containers killed seconds after they boot, before they
    can ever send a message — see investigation 2026-04-19."""
    from core.gateway.connection_pool import GatewayConnectionPool

    # Row entered running state 30 seconds ago — well inside the 5-min window.
    fresh_ts = _iso(datetime.now(timezone.utc) - timedelta(seconds=30))
    pool = GatewayConnectionPool(management_api=None)

    with (
        patch(
            "core.repositories.container_repo.get_by_status",
            new_callable=AsyncMock,
            return_value=[
                {
                    "owner_id": "user_fresh",
                    "status": "running",
                    "updated_at": fresh_ts,
                    "created_at": fresh_ts,
                }
            ],
        ),
        patch(
            "core.repositories.billing_repo.get_by_owner_id",
            new_callable=AsyncMock,
            return_value={"owner_id": "user_fresh", "plan_tier": "free"},
        ),
        patch("core.containers.get_ecs_manager") as mock_get_ecs,
    ):
        ecs = mock_get_ecs.return_value
        ecs.stop_user_service = AsyncMock()

        stopped = await pool._reap_once()

        ecs.stop_user_service.assert_not_awaited()
        assert stopped == []


@pytest.mark.asyncio
async def test_reaps_old_running_container_with_no_last_active_at():
    """A row that's been running for hours with no recorded activity (e.g.
    legacy row from before record_activity was implemented, or a container
    whose record_activity writes have been failing) should still get reaped
    once its updated_at falls outside the idle window."""
    from core.gateway.connection_pool import GatewayConnectionPool

    pool = GatewayConnectionPool(management_api=None)
    old_ts = _iso(datetime.now(timezone.utc) - timedelta(hours=1))

    with (
        patch(
            "core.repositories.container_repo.get_by_status",
            new_callable=AsyncMock,
            return_value=[
                {
                    "owner_id": "user_stale",
                    "status": "running",
                    "updated_at": old_ts,
                    "created_at": old_ts,
                }
            ],
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
async def test_reaps_row_with_no_timestamps_at_all():
    """Defense in depth: a row with no last_active_at, no updated_at, and
    no created_at falls all the way through the chain to epoch 0 and gets
    reaped. Should never happen in practice (DynamoDB rows always have
    created_at set by upsert) but the fallback chain shouldn't crash."""
    from core.gateway.connection_pool import GatewayConnectionPool

    pool = GatewayConnectionPool(management_api=None)

    with (
        patch(
            "core.repositories.container_repo.get_by_status",
            new_callable=AsyncMock,
            return_value=[{"owner_id": "user_no_ts", "status": "running"}],
        ),
        patch(
            "core.repositories.billing_repo.get_by_owner_id",
            new_callable=AsyncMock,
            return_value={"owner_id": "user_no_ts", "plan_tier": "free"},
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

        ecs.stop_user_service.assert_awaited_once_with("user_no_ts")
        assert stopped == ["user_no_ts"]


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


@pytest.mark.asyncio
async def test_reap_once_emits_both_gauges():
    """Every reaper cycle must emit both gateway.running.count (new, feeds P12
    heartbeat alarm) AND gateway.connection.open (legacy, feeds the W5 alarm
    which has treatMissingData=BREACHING). Dropping the legacy emission would
    leave W5 permanently in ALARM from absent datapoints."""
    from core.gateway.connection_pool import GatewayConnectionPool

    pool = GatewayConnectionPool(management_api=None)
    # Simulate two "open" backend↔gateway connections so the legacy gauge has
    # a non-zero sample to assert on.
    pool._connections = {"user_a": object(), "user_b": object()}  # type: ignore[assignment]

    with (
        patch(
            "core.repositories.container_repo.get_by_status",
            new_callable=AsyncMock,
            return_value=[{"owner_id": "user_a", "status": "running"}],
        ),
        patch(
            "core.repositories.billing_repo.get_by_owner_id",
            new_callable=AsyncMock,
            return_value={"owner_id": "user_a", "plan_tier": "starter"},
        ),
        patch("core.gateway.connection_pool.gauge") as mock_gauge,
    ):
        await pool._reap_once()

    metric_names = [call.args[0] for call in mock_gauge.call_args_list]
    assert "gateway.running.count" in metric_names
    assert "gateway.connection.open" in metric_names
    running_call = next(c for c in mock_gauge.call_args_list if c.args[0] == "gateway.running.count")
    open_call = next(c for c in mock_gauge.call_args_list if c.args[0] == "gateway.connection.open")
    assert running_call.args[1] == 1  # one row from get_by_status
    assert open_call.args[1] == 2  # two entries in pool._connections


@pytest.mark.asyncio
async def test_reap_once_emits_per_tier_running_count_breakdown():
    """Observability: in addition to the single gateway.running.count gauge,
    the reaper emits gateway.running.count.by_tier with a `tier` dimension so
    we can answer 'how many free vs paid containers are running right now'
    without log scraping."""
    from core.gateway.connection_pool import GatewayConnectionPool

    pool = GatewayConnectionPool(management_api=None)

    rows = [
        {"owner_id": "user_free_a", "status": "running"},
        {"owner_id": "user_free_b", "status": "running"},
        {"owner_id": "user_starter", "status": "running"},
        {"owner_id": "user_orphan", "status": "running"},
    ]

    async def fake_billing(oid):
        return {
            "user_free_a": {"plan_tier": "free"},
            "user_free_b": {"plan_tier": "free"},
            "user_starter": {"plan_tier": "starter"},
        }.get(oid)  # user_orphan returns None → defaults to "free"

    with (
        patch(
            "core.repositories.container_repo.get_by_status",
            new_callable=AsyncMock,
            return_value=rows,
        ),
        patch(
            "core.repositories.billing_repo.get_by_owner_id",
            new=AsyncMock(side_effect=fake_billing),
        ),
        patch("core.containers.get_ecs_manager"),
        patch("core.gateway.connection_pool.gauge") as mock_gauge,
    ):
        await pool._reap_once()

    # Filter only the by_tier gauge calls.
    by_tier_calls = [c for c in mock_gauge.call_args_list if c.args and c.args[0] == "gateway.running.count.by_tier"]
    breakdown = {c.kwargs.get("dimensions", {}).get("tier"): c.args[1] for c in by_tier_calls}
    # Two free users + the orphan (defaulted to free) = 3 free, 1 starter.
    assert breakdown == {"free": 3, "starter": 1}


@pytest.mark.asyncio
async def test_reap_once_caches_billing_lookup_failures_within_cycle():
    """Codex P2 regression on PR #273: a failed billing lookup must be cached
    for the rest of the cycle, otherwise the per-tier breakdown loop AND the
    idle-eligible reap loop both trigger a DDB get_by_owner_id call for the
    same failing owner — doubling read pressure and warning-log noise."""
    from core.gateway.connection_pool import GatewayConnectionPool

    old_ts = _iso(datetime.now(timezone.utc) - timedelta(minutes=30))
    pool = GatewayConnectionPool(management_api=None)

    # Same owner appears once in get_by_status. We expect billing to be
    # called exactly once even though _resolve_tier is invoked twice in
    # the cycle (once for the per-tier breakdown, once for the reap path).
    rows = [
        {"owner_id": "user_billing_broken", "status": "running", "last_active_at": old_ts},
    ]

    mock_billing = AsyncMock(side_effect=RuntimeError("billing down"))

    with (
        patch(
            "core.repositories.container_repo.get_by_status",
            new_callable=AsyncMock,
            return_value=rows,
        ),
        patch("core.repositories.billing_repo.get_by_owner_id", new=mock_billing),
        patch("core.containers.get_ecs_manager"),
    ):
        await pool._reap_once()

    # Without the per-cycle failure cache, billing would be called twice.
    assert mock_billing.await_count == 1
