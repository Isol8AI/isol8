"""Integration tests for the core user + billing lifecycle.

These tests exercise the full cross-service flow using a real PostgreSQL
database while mocking external APIs (Stripe, ECS, Workspace). They
verify that database state is consistent after each operation and that
services interact correctly — not just in isolation.

Flow under test:
    1. Clerk webhook → User + BillingAccount created in DB
    2. Stripe subscription webhook → plan upgraded + ECS provisioned
    3. Usage recorded → UsageEvent + UsageDaily + Stripe meter event
    4. Billing dashboard reflects usage
    5. Stripe subscription cancelled → plan reverted + ECS stopped
"""

import json
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from models.billing import BillingAccount, ModelPricing, UsageDaily, UsageEvent
from models.user import User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stripe_event(event_type: str, data: dict) -> dict:
    """Build a minimal Stripe event envelope."""
    return {"type": event_type, "data": {"object": data}}


def _make_stripe_mock(customer_id: str = "cus_int_test") -> MagicMock:
    """Return a MagicMock wired to look like the stripe module."""
    mock = MagicMock()
    mock.Customer.create.return_value = MagicMock(id=customer_id)
    mock.Webhook.construct_event.side_effect = lambda body, sig, secret: json.loads(body)
    mock.billing.MeterEvent.create.return_value = MagicMock(id="meter_evt_1")
    return mock


# ---------------------------------------------------------------------------
# Phase 1 — User signup via Clerk webhook
# ---------------------------------------------------------------------------


class TestUserSignupViaWebhook:
    """Clerk webhook creates User + BillingAccount rows in the DB."""

    @pytest.mark.asyncio
    async def test_user_created_webhook_persists_user(self, db_session, override_get_session_factory):
        """user.created webhook inserts a User row."""
        from main import app
        from core.database import get_session_factory

        payload = {
            "type": "user.created",
            "data": {
                "id": "user_int_signup_1",
                "email_addresses": [{"email_address": "alice@example.com"}],
            },
        }

        with (
            patch("routers.webhooks.verify_webhook", new_callable=AsyncMock) as mock_verify,
            patch("core.services.billing_service.stripe", _make_stripe_mock()),
        ):
            mock_verify.return_value = payload
            app.dependency_overrides[get_session_factory] = override_get_session_factory

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/webhooks/clerk",
                    json=payload,
                    headers={"svix-id": "t", "svix-timestamp": "0", "svix-signature": "s"},
                )

        app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["status"] == "processed"

        result = await db_session.execute(select(User).where(User.id == "user_int_signup_1"))
        user = result.scalar_one_or_none()
        assert user is not None

    @pytest.mark.asyncio
    async def test_user_created_webhook_creates_billing_account(self, db_session, override_get_session_factory):
        """user.created webhook creates a BillingAccount with the Stripe customer ID."""
        from main import app
        from core.database import get_session_factory

        stripe_mock = _make_stripe_mock("cus_int_signup_2")
        payload = {
            "type": "user.created",
            "data": {
                "id": "user_int_signup_2",
                "email_addresses": [{"email_address": "bob@example.com"}],
            },
        }

        with (
            patch("routers.webhooks.verify_webhook", new_callable=AsyncMock) as mock_verify,
            patch("core.services.billing_service.stripe", stripe_mock),
        ):
            mock_verify.return_value = payload
            app.dependency_overrides[get_session_factory] = override_get_session_factory

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                await client.post(
                    "/api/v1/webhooks/clerk",
                    json=payload,
                    headers={"svix-id": "t", "svix-timestamp": "0", "svix-signature": "s"},
                )

        app.dependency_overrides.clear()

        result = await db_session.execute(
            select(BillingAccount).where(BillingAccount.clerk_user_id == "user_int_signup_2")
        )
        account = result.scalar_one_or_none()
        assert account is not None
        assert account.stripe_customer_id == "cus_int_signup_2"
        assert account.plan_tier == "free"
        assert account.stripe_subscription_id is None

    @pytest.mark.asyncio
    async def test_duplicate_user_created_webhook_is_idempotent(self, db_session, override_get_session_factory):
        """Sending user.created twice does not create duplicate rows."""
        from main import app
        from core.database import get_session_factory

        stripe_mock = _make_stripe_mock("cus_int_signup_3")
        payload = {
            "type": "user.created",
            "data": {
                "id": "user_int_signup_3",
                "email_addresses": [{"email_address": "carol@example.com"}],
            },
        }

        with (
            patch("routers.webhooks.verify_webhook", new_callable=AsyncMock) as mock_verify,
            patch("core.services.billing_service.stripe", stripe_mock),
        ):
            mock_verify.return_value = payload
            app.dependency_overrides[get_session_factory] = override_get_session_factory

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r1 = await client.post(
                    "/api/v1/webhooks/clerk",
                    json=payload,
                    headers={"svix-id": "t1", "svix-timestamp": "0", "svix-signature": "s"},
                )
                r2 = await client.post(
                    "/api/v1/webhooks/clerk",
                    json=payload,
                    headers={"svix-id": "t2", "svix-timestamp": "0", "svix-signature": "s"},
                )

        app.dependency_overrides.clear()
        assert r1.status_code == 200
        assert r2.status_code == 200

        result = await db_session.execute(
            select(BillingAccount).where(BillingAccount.clerk_user_id == "user_int_signup_3")
        )
        rows = result.scalars().all()
        assert len(rows) == 1, "Should not have duplicate billing accounts"

    @pytest.mark.asyncio
    async def test_stripe_failure_does_not_fail_webhook(self, db_session, override_get_session_factory):
        """BillingService failure is swallowed — User is still created."""
        from main import app
        from core.database import get_session_factory

        stripe_mock = MagicMock()
        stripe_mock.Customer.create.side_effect = Exception("Stripe unavailable")

        payload = {
            "type": "user.created",
            "data": {
                "id": "user_int_signup_4",
                "email_addresses": [],
            },
        }

        with (
            patch("routers.webhooks.verify_webhook", new_callable=AsyncMock) as mock_verify,
            patch("core.services.billing_service.stripe", stripe_mock),
        ):
            mock_verify.return_value = payload
            app.dependency_overrides[get_session_factory] = override_get_session_factory

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/webhooks/clerk",
                    json=payload,
                    headers={"svix-id": "t", "svix-timestamp": "0", "svix-signature": "s"},
                )

        app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["status"] == "processed"

        # User row should exist
        result = await db_session.execute(select(User).where(User.id == "user_int_signup_4"))
        assert result.scalar_one_or_none() is not None


# ---------------------------------------------------------------------------
# Phase 2 — Stripe subscription webhooks
# ---------------------------------------------------------------------------


class TestStripeSubscriptionWebhooks:
    """Stripe webhooks drive plan upgrades, ECS provisioning, and cancellation."""

    @pytest.fixture
    async def billing_account(self, db_session):
        """Create a user + free billing account to receive subscription events."""
        user = User(id="user_int_stripe_1")
        db_session.add(user)
        account = BillingAccount(
            clerk_user_id="user_int_stripe_1",
            stripe_customer_id="cus_int_stripe_1",
        )
        db_session.add(account)
        await db_session.flush()
        return account

    @pytest.mark.asyncio
    async def test_subscription_created_upgrades_plan(self, db_session, billing_account, override_get_db):
        """customer.subscription.created updates plan_tier and subscription_id."""
        from main import app
        from core.database import get_db

        stripe_event_body = json.dumps(
            _stripe_event(
                "customer.subscription.created",
                {
                    "id": "sub_int_1",
                    "customer": "cus_int_stripe_1",
                    "metadata": {"plan_tier": "starter"},
                },
            )
        ).encode()

        mock_ecs = MagicMock()
        mock_ecs.create_user_service = AsyncMock(return_value="svc-user_int_stripe_1")
        mock_workspace = MagicMock()

        with (
            patch("core.services.billing_service.stripe") as _stripe_mock,
            patch("routers.billing.stripe") as billing_stripe_mock,
            patch("routers.billing.get_ecs_manager", return_value=mock_ecs),
            patch("routers.billing.get_workspace", return_value=mock_workspace),
        ):
            billing_stripe_mock.Webhook.construct_event.return_value = json.loads(stripe_event_body)
            billing_stripe_mock.STRIPE_WEBHOOK_SECRET = ""

            app.dependency_overrides[get_db] = override_get_db

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/billing/webhooks/stripe",
                    content=stripe_event_body,
                    headers={"stripe-signature": "test-sig"},
                )

        app.dependency_overrides.clear()
        assert resp.status_code == 200

        await db_session.refresh(billing_account)
        assert billing_account.plan_tier == "starter"
        assert billing_account.stripe_subscription_id == "sub_int_1"

    @pytest.mark.asyncio
    async def test_subscription_created_provisions_ecs_service(self, db_session, billing_account, override_get_db):
        """customer.subscription.created triggers ECS service creation."""
        from main import app
        from core.database import get_db

        stripe_event_body = json.dumps(
            _stripe_event(
                "customer.subscription.created",
                {
                    "id": "sub_int_2",
                    "customer": "cus_int_stripe_1",
                    "metadata": {"plan_tier": "starter"},
                },
            )
        ).encode()

        mock_ecs = MagicMock()
        mock_ecs.create_user_service = AsyncMock(return_value="svc-user_int_stripe_1")
        mock_workspace = MagicMock()

        with (
            patch("routers.billing.stripe") as billing_stripe_mock,
            patch("routers.billing.get_ecs_manager", return_value=mock_ecs),
            patch("routers.billing.get_workspace", return_value=mock_workspace),
        ):
            billing_stripe_mock.Webhook.construct_event.return_value = json.loads(stripe_event_body)

            app.dependency_overrides[get_db] = override_get_db

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                await client.post(
                    "/api/v1/billing/webhooks/stripe",
                    content=stripe_event_body,
                    headers={"stripe-signature": "test-sig"},
                )

        app.dependency_overrides.clear()
        mock_ecs.create_user_service.assert_called_once()
        call_args = mock_ecs.create_user_service.call_args
        assert call_args[0][0] == "user_int_stripe_1"  # user_id

    @pytest.mark.asyncio
    async def test_subscription_deleted_reverts_to_free(self, db_session, billing_account, override_get_db):
        """customer.subscription.deleted reverts plan to free and clears subscription_id."""
        from main import app
        from core.database import get_db

        # First, set the account to starter
        billing_account.plan_tier = "starter"
        billing_account.stripe_subscription_id = "sub_int_del_1"
        await db_session.flush()

        stripe_event_body = json.dumps(
            _stripe_event(
                "customer.subscription.deleted",
                {
                    "id": "sub_int_del_1",
                    "customer": "cus_int_stripe_1",
                },
            )
        ).encode()

        mock_ecs = MagicMock()
        mock_ecs.stop_user_service = AsyncMock()

        with (
            patch("routers.billing.stripe") as billing_stripe_mock,
            patch("routers.billing.get_ecs_manager", return_value=mock_ecs),
        ):
            billing_stripe_mock.Webhook.construct_event.return_value = json.loads(stripe_event_body)

            app.dependency_overrides[get_db] = override_get_db

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/billing/webhooks/stripe",
                    content=stripe_event_body,
                    headers={"stripe-signature": "test-sig"},
                )

        app.dependency_overrides.clear()
        assert resp.status_code == 200

        await db_session.refresh(billing_account)
        assert billing_account.plan_tier == "free"
        assert billing_account.stripe_subscription_id is None

    @pytest.mark.asyncio
    async def test_subscription_deleted_stops_ecs_service(self, db_session, billing_account, override_get_db):
        """customer.subscription.deleted calls ECS stop_user_service."""
        from main import app
        from core.database import get_db

        billing_account.plan_tier = "starter"
        billing_account.stripe_subscription_id = "sub_int_del_2"
        await db_session.flush()

        stripe_event_body = json.dumps(
            _stripe_event(
                "customer.subscription.deleted",
                {
                    "id": "sub_int_del_2",
                    "customer": "cus_int_stripe_1",
                },
            )
        ).encode()

        mock_ecs = MagicMock()
        mock_ecs.stop_user_service = AsyncMock()

        with (
            patch("routers.billing.stripe") as billing_stripe_mock,
            patch("routers.billing.get_ecs_manager", return_value=mock_ecs),
        ):
            billing_stripe_mock.Webhook.construct_event.return_value = json.loads(stripe_event_body)

            app.dependency_overrides[get_db] = override_get_db

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                await client.post(
                    "/api/v1/billing/webhooks/stripe",
                    content=stripe_event_body,
                    headers={"stripe-signature": "test-sig"},
                )

        app.dependency_overrides.clear()
        mock_ecs.stop_user_service.assert_called_once_with("user_int_stripe_1", db_session)

    @pytest.mark.asyncio
    async def test_ecs_failure_during_subscription_does_not_fail_webhook(
        self, db_session, billing_account, override_get_db
    ):
        """ECS provisioning failure is logged but the webhook still returns 200."""
        from main import app
        from core.database import get_db
        from core.containers.ecs_manager import EcsManagerError

        stripe_event_body = json.dumps(
            _stripe_event(
                "customer.subscription.created",
                {
                    "id": "sub_int_ecs_fail",
                    "customer": "cus_int_stripe_1",
                    "metadata": {"plan_tier": "starter"},
                },
            )
        ).encode()

        mock_ecs = MagicMock()
        mock_ecs.create_user_service = AsyncMock(side_effect=EcsManagerError("ECS unavailable"))
        mock_workspace = MagicMock()

        with (
            patch("routers.billing.stripe") as billing_stripe_mock,
            patch("routers.billing.get_ecs_manager", return_value=mock_ecs),
            patch("routers.billing.get_workspace", return_value=mock_workspace),
        ):
            billing_stripe_mock.Webhook.construct_event.return_value = json.loads(stripe_event_body)

            app.dependency_overrides[get_db] = override_get_db

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/billing/webhooks/stripe",
                    content=stripe_event_body,
                    headers={"stripe-signature": "test-sig"},
                )

        app.dependency_overrides.clear()
        assert resp.status_code == 200

        # Plan still upgraded even though ECS failed
        await db_session.refresh(billing_account)
        assert billing_account.plan_tier == "starter"


# ---------------------------------------------------------------------------
# Phase 3 — Usage recording and billing
# ---------------------------------------------------------------------------


class TestUsageRecordingFlow:
    """UsageService records events, rolls up daily totals, and reports to Stripe."""

    @pytest.fixture
    async def billing_setup(self, db_session):
        """Billing account + model pricing for usage tests."""
        user = User(id="user_int_usage_1")
        db_session.add(user)
        account = BillingAccount(
            clerk_user_id="user_int_usage_1",
            stripe_customer_id="cus_int_usage_1",
        )
        db_session.add(account)
        pricing = ModelPricing(
            model_id="anthropic.claude-3-5-sonnet-20241022-v2:0",
            display_name="Claude 3.5 Sonnet",
            input_cost_per_token=Decimal("0.000003"),
            output_cost_per_token=Decimal("0.000015"),
        )
        db_session.add(pricing)
        await db_session.flush()
        return account, pricing

    @pytest.mark.asyncio
    async def test_record_usage_creates_usage_event(self, db_session, billing_setup):
        """record_usage inserts a UsageEvent row with correct costs."""
        from core.services.usage_service import UsageService

        account, _ = billing_setup
        svc = UsageService(db_session)

        with patch("core.services.usage_service.stripe") as stripe_mock:
            stripe_mock.billing.MeterEvent.create.return_value = MagicMock(id="evt_1")
            event = await svc.record_usage(
                billing_account_id=account.id,
                clerk_user_id="user_int_usage_1",
                model_id="anthropic.claude-3-5-sonnet-20241022-v2:0",
                input_tokens=1000,
                output_tokens=200,
                source="chat",
                session_id="session_abc",
            )

        assert event.input_tokens == 1000
        assert event.output_tokens == 200
        # input: 1000 * 0.000003 = 0.003; output: 200 * 0.000015 = 0.003; total = 0.006
        assert event.total_cost == Decimal("0.006")
        assert event.source == "chat"

    @pytest.mark.asyncio
    async def test_record_usage_creates_daily_rollup(self, db_session, billing_setup):
        """record_usage upserts a UsageDaily row for the day."""
        from core.services.usage_service import UsageService

        account, _ = billing_setup
        svc = UsageService(db_session)

        with patch("core.services.usage_service.stripe") as stripe_mock:
            stripe_mock.billing.MeterEvent.create.return_value = MagicMock(id="evt_2")
            await svc.record_usage(
                billing_account_id=account.id,
                clerk_user_id="user_int_usage_1",
                model_id="anthropic.claude-3-5-sonnet-20241022-v2:0",
                input_tokens=500,
                output_tokens=100,
                source="chat",
            )

        result = await db_session.execute(select(UsageDaily).where(UsageDaily.billing_account_id == account.id))
        rows = result.scalars().all()
        assert len(rows) == 1
        assert rows[0].total_input_tokens == 500
        assert rows[0].total_output_tokens == 100
        assert rows[0].request_count == 1

    @pytest.mark.asyncio
    async def test_multiple_usage_events_accumulate_in_daily_rollup(self, db_session, billing_setup):
        """Multiple record_usage calls accumulate in the same daily row."""
        from core.services.usage_service import UsageService

        account, _ = billing_setup
        svc = UsageService(db_session)

        with patch("core.services.usage_service.stripe") as stripe_mock:
            stripe_mock.billing.MeterEvent.create.return_value = MagicMock(id="evt_x")
            for i in range(3):
                await svc.record_usage(
                    billing_account_id=account.id,
                    clerk_user_id="user_int_usage_1",
                    model_id="anthropic.claude-3-5-sonnet-20241022-v2:0",
                    input_tokens=100,
                    output_tokens=50,
                    source="chat",
                )

        result = await db_session.execute(select(UsageDaily).where(UsageDaily.billing_account_id == account.id))
        daily = result.scalar_one()
        assert daily.total_input_tokens == 300
        assert daily.total_output_tokens == 150
        assert daily.request_count == 3

    @pytest.mark.asyncio
    async def test_record_usage_reports_to_stripe(self, db_session, billing_setup):
        """record_usage calls stripe.billing.MeterEvent.create with microdollars."""
        from core.services.usage_service import UsageService

        account, _ = billing_setup
        svc = UsageService(db_session)

        with patch("core.services.usage_service.stripe") as stripe_mock:
            stripe_mock.billing.MeterEvent.create.return_value = MagicMock(id="evt_stripe")
            await svc.record_usage(
                billing_account_id=account.id,
                clerk_user_id="user_int_usage_1",
                model_id="anthropic.claude-3-5-sonnet-20241022-v2:0",
                input_tokens=1000,
                output_tokens=200,
                source="chat",
            )

        stripe_mock.billing.MeterEvent.create.assert_called_once()
        call_kwargs = stripe_mock.billing.MeterEvent.create.call_args[1]
        assert call_kwargs["event_name"] == "llm_token_usage"
        assert call_kwargs["payload"]["stripe_customer_id"] == "cus_int_usage_1"
        # billable = total_cost * markup (1.4) = 0.006 * 1.4 = 0.0084 → 8400 microdollars
        assert int(call_kwargs["payload"]["value"]) == 8400

    @pytest.mark.asyncio
    async def test_record_usage_fallback_pricing_when_model_not_found(self, db_session, billing_setup):
        """record_usage uses fallback pricing for unknown models."""
        from core.services.usage_service import UsageService

        account, _ = billing_setup
        svc = UsageService(db_session)

        with patch("core.services.usage_service.stripe") as stripe_mock:
            stripe_mock.billing.MeterEvent.create.return_value = MagicMock(id="evt_fallback")
            event = await svc.record_usage(
                billing_account_id=account.id,
                clerk_user_id="user_int_usage_1",
                model_id="unknown.model.v1",
                input_tokens=1000,
                output_tokens=200,
                source="chat",
            )

        # Fallback: input $3/1M, output $15/1M
        expected = Decimal("1000") * Decimal("0.000003") + Decimal("200") * Decimal("0.000015")
        assert event.total_cost == expected

    @pytest.mark.asyncio
    async def test_stripe_failure_does_not_fail_record_usage(self, db_session, billing_setup):
        """Stripe meter event failure is logged but usage is still written to DB."""
        from core.services.usage_service import UsageService

        account, _ = billing_setup
        svc = UsageService(db_session)

        with patch("core.services.usage_service.stripe") as stripe_mock:
            stripe_mock.billing.MeterEvent.create.side_effect = Exception("Stripe down")
            event = await svc.record_usage(
                billing_account_id=account.id,
                clerk_user_id="user_int_usage_1",
                model_id="anthropic.claude-3-5-sonnet-20241022-v2:0",
                input_tokens=100,
                output_tokens=50,
                source="chat",
            )

        # Event still written
        result = await db_session.execute(select(UsageEvent).where(UsageEvent.id == event.id))
        assert result.scalar_one_or_none() is not None
        # Stripe event ID is NULL (retry job picks it up)
        assert event.stripe_meter_event_id is None


# ---------------------------------------------------------------------------
# Phase 4 — Billing dashboard API
# ---------------------------------------------------------------------------


class TestBillingDashboardApi:
    """GET /api/v1/billing/* returns correct data reflecting DB state."""

    @pytest.fixture
    async def starter_user(self, db_session):
        """User with a starter subscription and some recorded usage."""
        user = User(id="user_test_123")  # matches mock_auth_context
        db_session.add(user)

        account = BillingAccount(
            clerk_user_id="user_test_123",
            stripe_customer_id="cus_int_dashboard_1",
            plan_tier="starter",
            stripe_subscription_id="sub_int_dashboard_1",
        )
        db_session.add(account)

        pricing = ModelPricing(
            model_id="anthropic.claude-3-5-sonnet-20241022-v2:0",
            display_name="Claude 3.5 Sonnet",
            input_cost_per_token=Decimal("0.000003"),
            output_cost_per_token=Decimal("0.000015"),
        )
        db_session.add(pricing)
        await db_session.flush()
        return account, pricing

    @pytest.mark.asyncio
    async def test_billing_account_reflects_plan_tier(self, async_client, starter_user):
        """GET /account returns the correct plan_tier from DB."""
        resp = await async_client.get("/api/v1/billing/account")
        assert resp.status_code == 200
        assert resp.json()["plan_tier"] == "starter"
        assert resp.json()["has_subscription"] is True

    @pytest.mark.asyncio
    async def test_billing_usage_reflects_recorded_events(self, db_session, async_client, starter_user):
        """GET /usage reflects usage events recorded via UsageService."""
        from core.services.usage_service import UsageService

        account, _ = starter_user
        svc = UsageService(db_session)

        with patch("core.services.usage_service.stripe") as stripe_mock:
            stripe_mock.billing.MeterEvent.create.return_value = MagicMock(id="evt_dash")
            await svc.record_usage(
                billing_account_id=account.id,
                clerk_user_id="user_test_123",
                model_id="anthropic.claude-3-5-sonnet-20241022-v2:0",
                input_tokens=2000,
                output_tokens=500,
                source="chat",
            )

        resp = await async_client.get("/api/v1/billing/usage")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_requests"] == 1
        assert data["total_cost"] > 0
        assert len(data["by_model"]) == 1

    @pytest.mark.asyncio
    async def test_billing_account_auto_creates_when_missing(self, async_client, db_session):
        """GET /account auto-creates BillingAccount when none exists (existing users)."""
        user = User(id="user_test_123")
        db_session.add(user)
        await db_session.flush()

        with patch("core.services.billing_service.stripe") as stripe_mock:
            stripe_mock.Customer.create.return_value = MagicMock(id="cus_auto")
            resp = await async_client.get("/api/v1/billing/account")

        assert resp.status_code == 200
        assert resp.json()["plan_tier"] == "free"
        assert resp.json()["has_subscription"] is False

        result = await db_session.execute(select(BillingAccount).where(BillingAccount.clerk_user_id == "user_test_123"))
        assert result.scalar_one_or_none() is not None


# ---------------------------------------------------------------------------
# Phase 5 — Full end-to-end cross-service flow
# ---------------------------------------------------------------------------


class TestFullUserLifecycleFlow:
    """Trace the complete user lifecycle: signup → subscribe → use → cancel."""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, db_session, override_get_db, override_get_session_factory):
        """
        Complete flow:
            1. Clerk webhook creates user + billing account
            2. Stripe webhook upgrades plan + provisions ECS
            3. Usage recorded via UsageService
            4. Billing dashboard shows correct state
            5. Stripe cancellation webhook reverts to free + stops ECS
        """
        from main import app
        from core.auth import get_current_user, AuthContext
        from core.database import get_db, get_session_factory

        USER_ID = "user_int_lifecycle_1"
        CUSTOMER_ID = "cus_int_lifecycle_1"
        SUB_ID = "sub_int_lifecycle_1"

        # --- Step 1: User signup ---
        stripe_mock = _make_stripe_mock(CUSTOMER_ID)
        clerk_payload = {
            "type": "user.created",
            "data": {
                "id": USER_ID,
                "email_addresses": [{"email_address": "lifecycle@example.com"}],
            },
        }

        with (
            patch("routers.webhooks.verify_webhook", new_callable=AsyncMock) as mock_verify,
            patch("core.services.billing_service.stripe", stripe_mock),
        ):
            mock_verify.return_value = clerk_payload
            app.dependency_overrides[get_session_factory] = override_get_session_factory

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(
                    "/api/v1/webhooks/clerk",
                    json=clerk_payload,
                    headers={"svix-id": "t", "svix-timestamp": "0", "svix-signature": "s"},
                )
        assert r.status_code == 200

        # Verify user + billing account created
        result = await db_session.execute(select(User).where(User.id == USER_ID))
        assert result.scalar_one_or_none() is not None
        result = await db_session.execute(select(BillingAccount).where(BillingAccount.clerk_user_id == USER_ID))
        account = result.scalar_one()
        assert account.plan_tier == "free"

        # --- Step 2: Stripe subscription.created ---
        sub_event_body = json.dumps(
            _stripe_event(
                "customer.subscription.created",
                {
                    "id": SUB_ID,
                    "customer": CUSTOMER_ID,
                    "metadata": {"plan_tier": "starter"},
                },
            )
        ).encode()

        mock_ecs = MagicMock()
        mock_ecs.create_user_service = AsyncMock(return_value=f"svc-{USER_ID}")
        mock_workspace = MagicMock()

        with (
            patch("routers.billing.stripe") as billing_stripe_mock,
            patch("routers.billing.get_ecs_manager", return_value=mock_ecs),
            patch("routers.billing.get_workspace", return_value=mock_workspace),
        ):
            billing_stripe_mock.Webhook.construct_event.return_value = json.loads(sub_event_body)
            app.dependency_overrides[get_db] = override_get_db

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(
                    "/api/v1/billing/webhooks/stripe",
                    content=sub_event_body,
                    headers={"stripe-signature": "sig"},
                )

        assert r.status_code == 200
        await db_session.refresh(account)
        assert account.plan_tier == "starter"
        assert account.stripe_subscription_id == SUB_ID
        mock_ecs.create_user_service.assert_called_once()

        # --- Step 3: Record usage ---
        pricing = ModelPricing(
            model_id="test.model",
            display_name="Test Model",
            input_cost_per_token=Decimal("0.000003"),
            output_cost_per_token=Decimal("0.000015"),
        )
        db_session.add(pricing)
        await db_session.flush()

        from core.services.usage_service import UsageService

        svc = UsageService(db_session)

        with patch("core.services.usage_service.stripe") as stripe_mock:
            stripe_mock.billing.MeterEvent.create.return_value = MagicMock(id="evt_lc")
            event = await svc.record_usage(
                billing_account_id=account.id,
                clerk_user_id=USER_ID,
                model_id="test.model",
                input_tokens=1000,
                output_tokens=500,
                source="chat",
            )

        assert event.billing_account_id == account.id
        result = await db_session.execute(select(UsageDaily).where(UsageDaily.billing_account_id == account.id))
        assert result.scalar_one_or_none() is not None

        # --- Step 4: Billing dashboard ---
        async def _mock_user():
            return AuthContext(user_id=USER_ID)

        app.dependency_overrides[get_current_user] = _mock_user
        app.dependency_overrides[get_db] = override_get_db

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/v1/billing/account")
        assert r.status_code == 200
        assert r.json()["plan_tier"] == "starter"
        assert r.json()["has_subscription"] is True

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/v1/billing/usage")
        assert r.status_code == 200
        assert r.json()["total_requests"] == 1

        # --- Step 5: Subscription cancelled ---
        cancel_event_body = json.dumps(
            _stripe_event(
                "customer.subscription.deleted",
                {"id": SUB_ID, "customer": CUSTOMER_ID},
            )
        ).encode()

        mock_ecs.stop_user_service = AsyncMock()

        with (
            patch("routers.billing.stripe") as billing_stripe_mock,
            patch("routers.billing.get_ecs_manager", return_value=mock_ecs),
        ):
            billing_stripe_mock.Webhook.construct_event.return_value = json.loads(cancel_event_body)
            app.dependency_overrides[get_db] = override_get_db

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(
                    "/api/v1/billing/webhooks/stripe",
                    content=cancel_event_body,
                    headers={"stripe-signature": "sig"},
                )

        assert r.status_code == 200
        await db_session.refresh(account)
        assert account.plan_tier == "free"
        assert account.stripe_subscription_id is None
        mock_ecs.stop_user_service.assert_called_once_with(USER_ID, db_session)

        app.dependency_overrides.clear()
