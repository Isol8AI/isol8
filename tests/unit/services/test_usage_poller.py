"""Tests for UsagePoller background billing sync."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.services.usage_poller import UsagePoller
from models.billing import BillingAccount, UsageEvent
from models.container import Container


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class _MockDbFactory:
    """Mock db_factory callable that returns a single async context manager."""

    def __init__(self, session):
        self._session = session

    def __call__(self):
        return self

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *_):
        pass


def _make_container(user_id="user_poll_123", status="running", gateway_token="tok-abc"):
    return Container(
        user_id=user_id,
        service_name="openclaw-abc123def456",
        gateway_token=gateway_token,
        status=status,
    )


# ---------------------------------------------------------------------------
# _get_recorded_tokens (uses real DB)
# ---------------------------------------------------------------------------


class TestGetRecordedTokens:
    """Test static method for summing recorded tokens per session."""

    @pytest.fixture
    async def account(self, db_session):
        acc = BillingAccount(clerk_user_id="user_poller_grt", stripe_customer_id="cus_grt_1")
        db_session.add(acc)
        await db_session.flush()
        return acc

    @pytest.mark.asyncio
    async def test_empty_when_no_events(self, db_session, account):
        result = await UsagePoller._get_recorded_tokens(db_session, account.id)
        assert result == {}

    @pytest.mark.asyncio
    async def test_returns_summed_tokens_per_session(self, db_session, account):
        """Tokens from multiple events for the same session are summed."""
        for _ in range(2):
            e = UsageEvent(
                billing_account_id=account.id,
                clerk_user_id="user_poller_grt",
                model_id="claude-3",
                input_tokens=100,
                output_tokens=50,
                input_cost=Decimal("0.0003"),
                output_cost=Decimal("0.00075"),
                total_cost=Decimal("0.00105"),
                billable_amount=Decimal("0.00147"),
                source="agent",
                session_id="sess-abc",
                month_partition="2024-01",
            )
            db_session.add(e)
        await db_session.flush()

        result = await UsagePoller._get_recorded_tokens(db_session, account.id)
        assert "sess-abc" in result
        assert result["sess-abc"]["input"] == 200
        assert result["sess-abc"]["output"] == 100

    @pytest.mark.asyncio
    async def test_multiple_sessions_tracked_separately(self, db_session, account):
        """Different sessions are tracked independently."""
        for sess in ["sess-1", "sess-2"]:
            e = UsageEvent(
                billing_account_id=account.id,
                clerk_user_id="user_poller_grt",
                model_id="claude-3",
                input_tokens=10,
                output_tokens=5,
                input_cost=Decimal("0.00003"),
                output_cost=Decimal("0.000075"),
                total_cost=Decimal("0.000105"),
                billable_amount=Decimal("0.000147"),
                source="agent",
                session_id=sess,
                month_partition="2024-01",
            )
            db_session.add(e)
        await db_session.flush()

        result = await UsagePoller._get_recorded_tokens(db_session, account.id)
        assert set(result.keys()) == {"sess-1", "sess-2"}
        assert result["sess-1"]["input"] == 10
        assert result["sess-2"]["input"] == 10

    @pytest.mark.asyncio
    async def test_ignores_events_without_session(self, db_session, account):
        """Events with session_id=None are excluded from the result."""
        e = UsageEvent(
            billing_account_id=account.id,
            clerk_user_id="user_poller_grt",
            model_id="claude-3",
            input_tokens=100,
            output_tokens=50,
            input_cost=Decimal("0.0003"),
            output_cost=Decimal("0.00075"),
            total_cost=Decimal("0.00105"),
            billable_amount=Decimal("0.00147"),
            source="chat",
            session_id=None,
            month_partition="2024-01",
        )
        db_session.add(e)
        await db_session.flush()

        result = await UsagePoller._get_recorded_tokens(db_session, account.id)
        assert result == {}

    @pytest.mark.asyncio
    async def test_only_counts_own_account(self, db_session):
        """Tokens for a different billing account are not included."""
        acc1 = BillingAccount(clerk_user_id="user_poll_a1", stripe_customer_id="cus_poll_a1")
        acc2 = BillingAccount(clerk_user_id="user_poll_a2", stripe_customer_id="cus_poll_a2")
        db_session.add(acc1)
        db_session.add(acc2)
        await db_session.flush()

        e = UsageEvent(
            billing_account_id=acc2.id,
            clerk_user_id="user_poll_a2",
            model_id="claude-3",
            input_tokens=500,
            output_tokens=250,
            input_cost=Decimal("0.0015"),
            output_cost=Decimal("0.00375"),
            total_cost=Decimal("0.00525"),
            billable_amount=Decimal("0.00735"),
            source="agent",
            session_id="sess-other",
            month_partition="2024-01",
        )
        db_session.add(e)
        await db_session.flush()

        result = await UsagePoller._get_recorded_tokens(db_session, acc1.id)
        assert result == {}


# ---------------------------------------------------------------------------
# _sync_user (uses mocks — no real DB needed)
# ---------------------------------------------------------------------------


class TestSyncUser:
    """Test single-user sync logic with mocked dependencies."""

    def _make_poller(self, mock_session):
        db_factory = _MockDbFactory(mock_session)
        return UsagePoller(db_factory)

    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.add = MagicMock()
        return db

    @pytest.fixture
    def mock_ecs(self):
        ecs = AsyncMock()
        ecs.resolve_running_container = AsyncMock(return_value=(_make_container(), "10.0.0.1"))
        return ecs

    @pytest.fixture
    def mock_pool(self):
        pool = AsyncMock()
        pool.send_rpc = AsyncMock(
            return_value={
                "sessions": [
                    {
                        "key": "sess-xyz",
                        "inputTokens": 200,
                        "outputTokens": 100,
                        "model": "claude-3-5-sonnet",
                        "agentId": "goose",
                    }
                ]
            }
        )
        return pool

    @pytest.mark.asyncio
    async def test_returns_zero_when_container_not_found(self, mock_db, mock_ecs, mock_pool):
        """Returns 0 if container cannot be resolved."""
        mock_ecs.resolve_running_container = AsyncMock(return_value=(None, None))
        poller = self._make_poller(mock_db)
        result = await poller._sync_user("user_x", "token", mock_pool, mock_ecs)
        assert result == 0

    @pytest.mark.asyncio
    async def test_returns_zero_when_ip_not_found(self, mock_db, mock_ecs, mock_pool):
        """Returns 0 if container exists but has no IP (still provisioning)."""
        mock_ecs.resolve_running_container = AsyncMock(return_value=(_make_container(), None))
        poller = self._make_poller(mock_db)
        result = await poller._sync_user("user_x", "token", mock_pool, mock_ecs)
        assert result == 0

    @pytest.mark.asyncio
    @patch("core.services.usage_service.UsageService")
    async def test_returns_zero_when_gateway_unreachable(self, MockUsageService, mock_db, mock_ecs, mock_pool):
        """Returns 0 gracefully when gateway RPC throws (e.g. connection refused)."""
        mock_pool.send_rpc = AsyncMock(side_effect=ConnectionRefusedError("refused"))
        poller = self._make_poller(mock_db)
        result = await poller._sync_user("user_x", "token", mock_pool, mock_ecs)
        assert result == 0

    @pytest.mark.asyncio
    @patch("core.services.usage_service.UsageService")
    async def test_returns_zero_when_no_sessions(self, MockUsageService, mock_db, mock_ecs, mock_pool):
        """Returns 0 when gateway returns empty sessions list."""
        mock_pool.send_rpc = AsyncMock(return_value={"sessions": []})
        poller = self._make_poller(mock_db)
        result = await poller._sync_user("user_x", "token", mock_pool, mock_ecs)
        assert result == 0

    @pytest.mark.asyncio
    @patch("core.services.usage_service.UsageService")
    async def test_returns_zero_when_no_billing_account(self, MockUsageService, mock_db, mock_ecs, mock_pool):
        """Returns 0 when user has no billing account."""
        mock_svc_instance = AsyncMock()
        mock_svc_instance.get_billing_account_for_user = AsyncMock(return_value=None)
        MockUsageService.return_value = mock_svc_instance
        poller = self._make_poller(mock_db)
        result = await poller._sync_user("user_x", "token", mock_pool, mock_ecs)
        assert result == 0

    @pytest.mark.asyncio
    @patch("core.services.usage_service.UsageService")
    async def test_records_delta_for_new_session(self, MockUsageService, mock_db, mock_ecs, mock_pool):
        """Records tokens for a session not previously seen (delta = full count)."""
        mock_account = MagicMock()
        mock_account.id = "account-uuid-1"
        mock_svc_instance = AsyncMock()
        mock_svc_instance.get_billing_account_for_user = AsyncMock(return_value=mock_account)
        mock_svc_instance.record_usage = AsyncMock()
        MockUsageService.return_value = mock_svc_instance

        # Mock _get_recorded_tokens: no prior tokens
        with patch.object(UsagePoller, "_get_recorded_tokens", AsyncMock(return_value={})):
            poller = self._make_poller(mock_db)
            result = await poller._sync_user("user_x", "token", mock_pool, mock_ecs)

        assert result == 1
        mock_svc_instance.record_usage.assert_awaited_once()
        call_kwargs = mock_svc_instance.record_usage.call_args.kwargs
        assert call_kwargs["input_tokens"] == 200
        assert call_kwargs["output_tokens"] == 100
        assert call_kwargs["model_id"] == "claude-3-5-sonnet"
        assert call_kwargs["session_id"] == "sess-xyz"
        assert call_kwargs["source"] == "agent"

    @pytest.mark.asyncio
    @patch("core.services.usage_service.UsageService")
    async def test_records_only_delta_tokens(self, MockUsageService, mock_db, mock_ecs, mock_pool):
        """Only records the difference since last recorded tokens."""
        mock_account = MagicMock()
        mock_account.id = "account-uuid-2"
        mock_svc_instance = AsyncMock()
        mock_svc_instance.get_billing_account_for_user = AsyncMock(return_value=mock_account)
        mock_svc_instance.record_usage = AsyncMock()
        MockUsageService.return_value = mock_svc_instance

        # Previously recorded 100 input, 50 output for this session
        with patch.object(
            UsagePoller,
            "_get_recorded_tokens",
            AsyncMock(return_value={"sess-xyz": {"input": 100, "output": 50}}),
        ):
            poller = self._make_poller(mock_db)
            result = await poller._sync_user("user_x", "token", mock_pool, mock_ecs)

        assert result == 1
        call_kwargs = mock_svc_instance.record_usage.call_args.kwargs
        # delta: 200 - 100 = 100 input, 100 - 50 = 50 output
        assert call_kwargs["input_tokens"] == 100
        assert call_kwargs["output_tokens"] == 50

    @pytest.mark.asyncio
    @patch("core.services.usage_service.UsageService")
    async def test_skips_session_with_zero_delta(self, MockUsageService, mock_db, mock_ecs, mock_pool):
        """Skips recording when both input and output deltas are zero."""
        mock_account = MagicMock()
        mock_account.id = "account-uuid-3"
        mock_svc_instance = AsyncMock()
        mock_svc_instance.get_billing_account_for_user = AsyncMock(return_value=mock_account)
        mock_svc_instance.record_usage = AsyncMock()
        MockUsageService.return_value = mock_svc_instance

        # Already recorded the exact same counts
        with patch.object(
            UsagePoller,
            "_get_recorded_tokens",
            AsyncMock(return_value={"sess-xyz": {"input": 200, "output": 100}}),
        ):
            poller = self._make_poller(mock_db)
            result = await poller._sync_user("user_x", "token", mock_pool, mock_ecs)

        assert result == 0
        mock_svc_instance.record_usage.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("core.services.usage_service.UsageService")
    async def test_zero_delta_guard_prevents_negative(self, MockUsageService, mock_db, mock_ecs, mock_pool):
        """Delta is clamped to 0 even if gateway returns fewer tokens than recorded (e.g. session reset)."""
        mock_account = MagicMock()
        mock_account.id = "account-uuid-4"
        mock_svc_instance = AsyncMock()
        mock_svc_instance.get_billing_account_for_user = AsyncMock(return_value=mock_account)
        mock_svc_instance.record_usage = AsyncMock()
        MockUsageService.return_value = mock_svc_instance

        # Previously recorded MORE tokens than current gateway reports
        with patch.object(
            UsagePoller,
            "_get_recorded_tokens",
            AsyncMock(return_value={"sess-xyz": {"input": 999, "output": 500}}),
        ):
            poller = self._make_poller(mock_db)
            result = await poller._sync_user("user_x", "token", mock_pool, mock_ecs)

        assert result == 0
        mock_svc_instance.record_usage.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("core.services.usage_service.UsageService")
    async def test_skips_sessions_without_key(self, MockUsageService, mock_db, mock_ecs, mock_pool):
        """Sessions with empty or missing key are skipped."""
        mock_pool.send_rpc = AsyncMock(
            return_value={
                "sessions": [
                    {"key": "", "inputTokens": 100, "outputTokens": 50, "model": "claude"},
                    {"inputTokens": 100, "outputTokens": 50, "model": "claude"},
                ]
            }
        )
        mock_account = MagicMock()
        mock_account.id = "account-uuid-5"
        mock_svc_instance = AsyncMock()
        mock_svc_instance.get_billing_account_for_user = AsyncMock(return_value=mock_account)
        mock_svc_instance.record_usage = AsyncMock()
        MockUsageService.return_value = mock_svc_instance

        with patch.object(UsagePoller, "_get_recorded_tokens", AsyncMock(return_value={})):
            poller = self._make_poller(mock_db)
            result = await poller._sync_user("user_x", "token", mock_pool, mock_ecs)

        assert result == 0
        mock_svc_instance.record_usage.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("core.services.usage_service.UsageService")
    async def test_continues_after_record_failure(self, MockUsageService, mock_db, mock_ecs, mock_pool):
        """If one session fails to record, subsequent sessions still process."""
        mock_pool.send_rpc = AsyncMock(
            return_value={
                "sessions": [
                    {"key": "sess-1", "inputTokens": 100, "outputTokens": 50, "model": "claude"},
                    {"key": "sess-2", "inputTokens": 200, "outputTokens": 100, "model": "claude"},
                ]
            }
        )
        mock_account = MagicMock()
        mock_account.id = "account-uuid-6"
        mock_svc_instance = AsyncMock()
        mock_svc_instance.get_billing_account_for_user = AsyncMock(return_value=mock_account)
        # First call fails, second succeeds
        mock_svc_instance.record_usage = AsyncMock(side_effect=[Exception("DB error"), None])
        MockUsageService.return_value = mock_svc_instance

        with patch.object(UsagePoller, "_get_recorded_tokens", AsyncMock(return_value={})):
            poller = self._make_poller(mock_db)
            result = await poller._sync_user("user_x", "token", mock_pool, mock_ecs)

        # Second session still recorded despite first failure
        assert result == 1


# ---------------------------------------------------------------------------
# _poll_all_users (uses mocks)
# ---------------------------------------------------------------------------


class TestPollAllUsers:
    """Test the top-level polling loop."""

    @pytest.mark.asyncio
    async def test_returns_early_when_no_containers(self):
        """If no running containers, skips polling entirely."""
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        db_factory = _MockDbFactory(mock_db)
        poller = UsagePoller(db_factory)

        with (
            patch("core.containers.get_gateway_pool") as mock_get_pool,
            patch("core.containers.get_ecs_manager") as mock_get_ecs,
        ):
            await poller._poll_all_users()
            # Pool and ECS are still fetched even with no containers
            mock_get_pool.assert_called_once()
            mock_get_ecs.assert_called_once()

    @pytest.mark.asyncio
    async def test_syncs_each_running_container(self):
        """Calls _sync_user once per running container."""
        containers = [
            _make_container("user_a", gateway_token="tok-a"),
            _make_container("user_b", gateway_token="tok-b"),
        ]
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = containers
        mock_db.execute = AsyncMock(return_value=mock_result)

        db_factory = _MockDbFactory(mock_db)
        poller = UsagePoller(db_factory)

        with (
            patch("core.containers.get_gateway_pool", return_value=MagicMock()),
            patch("core.containers.get_ecs_manager", return_value=MagicMock()),
            patch.object(poller, "_sync_user", AsyncMock(return_value=1)) as mock_sync,
        ):
            await poller._poll_all_users()

        assert mock_sync.await_count == 2
        user_ids = {call.args[0] for call in mock_sync.await_args_list}
        assert user_ids == {"user_a", "user_b"}

    @pytest.mark.asyncio
    async def test_continues_after_sync_failure(self):
        """Failure syncing one user does not stop polling for others."""
        containers = [
            _make_container("user_fail", gateway_token="tok-f"),
            _make_container("user_ok", gateway_token="tok-ok"),
        ]
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = containers
        mock_db.execute = AsyncMock(return_value=mock_result)

        db_factory = _MockDbFactory(mock_db)
        poller = UsagePoller(db_factory)

        sync_results = {"user_fail": Exception("boom"), "user_ok": 2}

        async def fake_sync(user_id, token, pool, ecs):
            r = sync_results[user_id]
            if isinstance(r, Exception):
                raise r
            return r

        with (
            patch("core.containers.get_gateway_pool", return_value=MagicMock()),
            patch("core.containers.get_ecs_manager", return_value=MagicMock()),
            patch.object(poller, "_sync_user", side_effect=fake_sync),
        ):
            # Should not raise
            await poller._poll_all_users()


# ---------------------------------------------------------------------------
# Lifecycle (start/stop)
# ---------------------------------------------------------------------------


class TestUsagePollerLifecycle:
    """Test start/stop task management."""

    @pytest.mark.asyncio
    async def test_start_creates_task(self):
        poller = UsagePoller(_MockDbFactory(AsyncMock()))
        with patch.object(poller, "_loop", AsyncMock()):
            await poller.start()
            assert poller._running is True
            assert poller._task is not None
            await poller.stop()

    @pytest.mark.asyncio
    async def test_start_is_idempotent(self):
        """Calling start twice does not create a second task."""
        poller = UsagePoller(_MockDbFactory(AsyncMock()))
        with patch.object(poller, "_loop", AsyncMock()):
            await poller.start()
            task1 = poller._task
            await poller.start()
            assert poller._task is task1
            await poller.stop()

    @pytest.mark.asyncio
    async def test_stop_sets_running_false(self):
        poller = UsagePoller(_MockDbFactory(AsyncMock()))
        with patch.object(poller, "_loop", AsyncMock()):
            await poller.start()
            await poller.stop()
            assert poller._running is False
