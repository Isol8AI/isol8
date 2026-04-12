"""Tests for billing API endpoints — hybrid tier model."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestGetBillingAccount:
    """Test GET /api/v1/billing/account."""

    @pytest.mark.asyncio
    @patch("routers.billing.usage_repo")
    @patch("routers.billing.check_budget")
    @patch("routers.billing.billing_repo")
    async def test_get_billing_account(self, mock_repo, mock_check_budget, mock_usage_repo, async_client):
        """Should return billing account with real budget data."""
        mock_repo.get_by_owner_id = AsyncMock(
            return_value={
                "owner_id": "user_test_123",
                "stripe_customer_id": "cus_billing_test",
                "plan_tier": "starter",
                "stripe_subscription_id": "sub_123",
            }
        )
        mock_check_budget.return_value = {
            "allowed": True,
            "within_included": True,
            "overage_available": False,
            "overage_enabled": False,
            "current_spend": 3.50,
            "included_budget": 10.0,
            "is_subscribed": True,
            "tier": "starter",
        }
        mock_usage_repo.get_period_usage = AsyncMock(return_value={"total_spend_microdollars": 5_000_000})

        response = await async_client.get("/api/v1/billing/account")
        assert response.status_code == 200
        data = response.json()
        assert data["tier"] == "starter"
        assert data["is_subscribed"] is True
        assert data["current_spend"] == 3.50
        assert data["included_budget"] == 10.0
        assert data["budget_percent"] == 35.0
        assert data["lifetime_spend"] == 5.0
        assert data["within_included"] is True

    @pytest.mark.asyncio
    @patch("routers.billing.usage_repo")
    @patch("routers.billing.check_budget")
    @patch("routers.billing.billing_repo")
    @patch("core.services.billing_service.stripe")
    @patch("core.services.billing_service.billing_repo")
    async def test_get_billing_account_returns_free_defaults_without_creating(
        self, mock_svc_repo, mock_stripe, mock_router_repo, mock_check_budget, mock_usage_repo, async_client
    ):
        """GET /billing/account returns synthetic free-tier defaults when no
        row exists — it must NOT auto-create a Stripe customer or billing row.

        Regression: previously GET /billing/account called
        create_customer_for_owner on miss, which created a phantom
        personal-context row for every user whose ChatLayout mounted before
        their org was active. After the fix, the row is only created by
        POST /billing/checkout (the explicit subscribe intent, admin-gated).
        """
        mock_router_repo.get_by_owner_id = AsyncMock(return_value=None)
        mock_check_budget.return_value = {
            "allowed": True,
            "within_included": True,
            "overage_available": False,
            "overage_enabled": False,
            "current_spend": 0,
            "included_budget": 2.0,
            "is_subscribed": False,
            "tier": "free",
        }
        mock_usage_repo.get_period_usage = AsyncMock(return_value=None)

        response = await async_client.get("/api/v1/billing/account")

        assert response.status_code == 200
        data = response.json()
        assert data["tier"] == "free"
        assert data["is_subscribed"] is False
        assert data["budget_percent"] == 0.0
        assert data["overage_limit"] is None

        # Most important assertion: NO auto-create happened. Neither a Stripe
        # Customer nor a billing_repo write was issued.
        mock_stripe.Customer.create.assert_not_called()
        mock_svc_repo.create_if_not_exists.assert_not_called()


class TestGetUsage:
    """Test GET /api/v1/billing/usage."""

    @pytest.mark.asyncio
    @patch("routers.billing.get_usage_summary")
    async def test_get_usage_returns_summary(self, mock_get_summary, async_client):
        """Should return usage summary for personal user."""
        mock_get_summary.return_value = {
            "period": "2026-03",
            "total_spend": 5.25,
            "total_input_tokens": 10000,
            "total_output_tokens": 5000,
            "total_cache_read_tokens": 200,
            "total_cache_write_tokens": 100,
            "request_count": 42,
            "lifetime_spend": 15.75,
        }

        response = await async_client.get("/api/v1/billing/usage")
        assert response.status_code == 200
        data = response.json()
        assert data["total_spend"] == 5.25
        assert data["request_count"] == 42
        assert data["lifetime_spend"] == 15.75
        assert data["by_member"] == []


class TestGetMyUsage:
    """Test GET /api/v1/billing/my-usage."""

    @pytest.mark.asyncio
    @patch("routers.billing.usage_repo")
    async def test_get_my_usage_with_data(self, mock_usage_repo, async_client):
        """Should return current user's own usage for the billing period."""
        mock_usage_repo.get_period_usage = AsyncMock(
            return_value={
                "total_spend_microdollars": 3_500_000,
                "total_input_tokens": 8000,
                "total_output_tokens": 4000,
                "total_cache_read_tokens": 100,
                "total_cache_write_tokens": 50,
                "request_count": 25,
            }
        )

        response = await async_client.get("/api/v1/billing/my-usage")
        assert response.status_code == 200
        data = response.json()
        assert data["total_spend"] == 3.5
        assert data["total_input_tokens"] == 8000
        assert data["total_output_tokens"] == 4000
        assert data["request_count"] == 25
        assert "period" in data

        # Verify it was called with the member key pattern
        call_args = mock_usage_repo.get_period_usage.call_args
        assert call_args[0][0] == "user_test_123"  # owner_id
        assert call_args[0][1].startswith("member:user_test_123:")  # member key

    @pytest.mark.asyncio
    @patch("routers.billing.usage_repo")
    async def test_get_my_usage_no_data(self, mock_usage_repo, async_client):
        """Should return zeros when user has no usage data."""
        mock_usage_repo.get_period_usage = AsyncMock(return_value=None)

        response = await async_client.get("/api/v1/billing/my-usage")
        assert response.status_code == 200
        data = response.json()
        assert data["total_spend"] == 0.0
        assert data["total_input_tokens"] == 0
        assert data["total_output_tokens"] == 0
        assert data["request_count"] == 0


class TestGetPricing:
    """Test GET /api/v1/billing/pricing."""

    @pytest.mark.asyncio
    @patch("routers.billing.get_all_prices")
    @patch("routers.billing.billing_repo")
    async def test_get_pricing(self, mock_repo, mock_get_prices, async_client):
        """Should return model pricing with markup."""
        mock_repo.get_by_owner_id = AsyncMock(return_value={"owner_id": "user_test_123", "plan_tier": "free"})
        mock_get_prices.return_value = {
            "minimax.minimax-m2.5": {
                "input": 0.30e-6,
                "output": 1.20e-6,
                "cache_read": 0.0,
                "cache_write": 0.0,
            }
        }

        response = await async_client.get("/api/v1/billing/pricing")
        assert response.status_code == 200
        data = response.json()
        assert "minimax.minimax-m2.5" in data["models"]
        assert data["markup"] == 1.4
        assert data["tier_model"] is not None


class TestCheckout:
    """Test POST /api/v1/billing/checkout."""

    @pytest.mark.asyncio
    @patch("routers.billing.billing_repo")
    @patch("core.services.billing_service.TIER_PRICES", {"starter": "price_starter"})
    @patch("core.services.billing_service.METERED_PRICE_ID", "price_metered_test")
    @patch("core.services.billing_service.stripe")
    async def test_create_checkout_only_attaches_fixed_tier_item(self, mock_stripe, mock_repo, async_client):
        """Initial checkout must include ONLY the fixed-price tier line item.

        Regression: previously the metered overage line item
        (STRIPE_METERED_PRICE_ID) was always attached at checkout time, which
        produced a confusing two-line Stripe Checkout page where users thought
        they were subscribing to two products. The metered item is now only
        attached when the user explicitly toggles overage on via PUT
        /billing/overage — see `set_metered_overage_item` in billing_service.
        """
        mock_repo.get_by_owner_id = AsyncMock(
            return_value={
                "owner_id": "user_test_123",
                "stripe_customer_id": "cus_checkout_test",
                "plan_tier": "free",
            }
        )
        mock_stripe.checkout.Session.create.return_value = MagicMock(url="https://checkout.stripe.com/test_session")

        response = await async_client.post(
            "/api/v1/billing/checkout",
            json={"tier": "starter"},
        )
        assert response.status_code == 200
        assert "checkout_url" in response.json()

        # Critical assertion: exactly one line item, the fixed-price tier.
        # No metered overage line item, even though METERED_PRICE_ID is
        # configured (patched to "price_metered_test" above).
        mock_stripe.checkout.Session.create.assert_called_once()
        call_kwargs = mock_stripe.checkout.Session.create.call_args.kwargs
        assert call_kwargs["line_items"] == [{"price": "price_starter", "quantity": 1}]

    @pytest.mark.asyncio
    @patch("routers.billing.billing_repo")
    @patch("core.services.billing_service.TIER_PRICES", {"starter": "price_starter"})
    @patch("core.services.billing_service.billing_repo")
    @patch("core.services.billing_service.stripe")
    async def test_create_checkout_passes_email_to_stripe_when_customer_is_new(
        self,
        mock_stripe,
        mock_svc_repo,
        mock_router_repo,
        async_client,
    ):
        """When the caller has no billing row yet, /billing/checkout creates a
        new Stripe customer and the AuthContext.email must be passed through
        so the customer is born identifiable in the Stripe dashboard.

        Regression: previously the email parameter wasn't plumbed through, so
        every customer created on a Subscribe click had `email=None` until
        Stripe Checkout's form back-filled it (and only if the user actually
        completed Checkout — bail-outs were anonymous orphans forever).
        """
        from core.auth import AuthContext, get_current_user
        from main import app

        # Override get_current_user to inject an email-bearing AuthContext.
        # The default conftest fixture sets email=None, which would just
        # pass an empty string through and tell us nothing.
        async def auth_with_email() -> AuthContext:
            return AuthContext(user_id="user_test_123", email="prabu@example.com")

        app.dependency_overrides[get_current_user] = auth_with_email
        try:
            # No existing billing row → checkout will create one.
            mock_router_repo.get_by_owner_id = AsyncMock(return_value=None)
            mock_svc_repo.get_by_owner_id = AsyncMock(return_value=None)
            mock_svc_repo.create_if_not_exists = AsyncMock(
                return_value={
                    "owner_id": "user_test_123",
                    "stripe_customer_id": "cus_new_with_email",
                    "plan_tier": "free",
                    "stripe_subscription_id": None,
                }
            )
            mock_stripe.Customer.create.return_value = MagicMock(id="cus_new_with_email")
            mock_stripe.checkout.Session.create.return_value = MagicMock(url="https://checkout.stripe.com/test_session")

            response = await async_client.post(
                "/api/v1/billing/checkout",
                json={"tier": "starter"},
            )

            assert response.status_code == 200
            # The critical assertion: Stripe.Customer.create was called with
            # the email from AuthContext, not None / not empty.
            mock_stripe.Customer.create.assert_called_once()
            call_kwargs = mock_stripe.Customer.create.call_args.kwargs
            assert call_kwargs["email"] == "prabu@example.com"
        finally:
            app.dependency_overrides.pop(get_current_user, None)


class TestOverageToggle:
    """Test PUT /api/v1/billing/overage.

    The toggle now does TWO things in sequence:
      1. Stripe: attach (or detach) the metered overage line item on the
         user's active subscription via `Subscription.modify`.
      2. DynamoDB: flip the `overage_enabled` flag.

    Stripe-first ordering matters: if the Stripe write fails the DB stays
    untouched, so we never end up in a state where the DB says "overage on"
    but the subscription has no metered item (which would silently drop
    meter events and the customer wouldn't get billed for usage).
    """

    @pytest.mark.asyncio
    @patch("routers.billing.billing_repo")
    @patch("core.services.billing_service.METERED_PRICE_ID", "price_metered_test")
    @patch("core.services.billing_service.stripe")
    async def test_toggle_overage_on_attaches_metered_item_to_subscription(self, mock_stripe, mock_repo, async_client):
        """Toggling overage ON adds the metered line item to the existing
        Stripe subscription AND flips the DynamoDB flag."""
        mock_repo.get_by_owner_id = AsyncMock(
            return_value={
                "owner_id": "user_test_123",
                "stripe_customer_id": "cus_test",
                "stripe_subscription_id": "sub_test_123",
                "plan_tier": "starter",
            }
        )
        mock_repo.set_overage_enabled = AsyncMock(return_value={})
        # Subscription currently has only the fixed tier item (the new
        # post-checkout state), no metered item yet.
        mock_stripe.Subscription.retrieve.return_value = {
            "items": {
                "data": [
                    {"id": "si_fixed", "price": {"id": "price_starter"}},
                ]
            }
        }

        response = await async_client.put(
            "/api/v1/billing/overage",
            json={"enabled": True, "limit_dollars": 50.0},
        )
        assert response.status_code == 200

        # Stripe: metered item ADDED to the existing subscription
        mock_stripe.Subscription.modify.assert_called_once_with(
            "sub_test_123",
            items=[{"price": "price_metered_test"}],
        )
        # DynamoDB: flag flipped on
        mock_repo.set_overage_enabled.assert_called_once_with("user_test_123", True, overage_limit=50_000_000)

    @pytest.mark.asyncio
    @patch("routers.billing.billing_repo")
    @patch("core.services.billing_service.METERED_PRICE_ID", "price_metered_test")
    @patch("core.services.billing_service.stripe")
    async def test_toggle_overage_off_removes_metered_item_from_subscription(
        self, mock_stripe, mock_repo, async_client
    ):
        """Toggling overage OFF removes the metered line item from the
        existing Stripe subscription AND flips the DynamoDB flag."""
        mock_repo.get_by_owner_id = AsyncMock(
            return_value={
                "owner_id": "user_test_123",
                "stripe_customer_id": "cus_test",
                "stripe_subscription_id": "sub_test_123",
                "plan_tier": "starter",
            }
        )
        mock_repo.set_overage_enabled = AsyncMock(return_value={})
        # Subscription has BOTH the fixed item AND the metered item.
        mock_stripe.Subscription.retrieve.return_value = {
            "items": {
                "data": [
                    {"id": "si_fixed", "price": {"id": "price_starter"}},
                    {"id": "si_metered", "price": {"id": "price_metered_test"}},
                ]
            }
        }

        response = await async_client.put(
            "/api/v1/billing/overage",
            json={"enabled": False},
        )
        assert response.status_code == 200

        # Stripe: metered item REMOVED via deleted=true on its item id
        mock_stripe.Subscription.modify.assert_called_once_with(
            "sub_test_123",
            items=[{"id": "si_metered", "deleted": True}],
        )
        # DynamoDB: flag flipped off
        mock_repo.set_overage_enabled.assert_called_once_with("user_test_123", False, overage_limit=None)

    @pytest.mark.asyncio
    @patch("routers.billing.billing_repo")
    @patch("core.services.billing_service.METERED_PRICE_ID", "price_metered_test")
    @patch("core.services.billing_service.stripe")
    async def test_toggle_overage_on_is_idempotent_when_item_already_present(
        self, mock_stripe, mock_repo, async_client
    ):
        """Toggling on when the metered item is already attached must be a
        no-op on Stripe (no Subscription.modify call) but still update the
        DynamoDB row (e.g. limit change without a state change)."""
        mock_repo.get_by_owner_id = AsyncMock(
            return_value={
                "owner_id": "user_test_123",
                "stripe_customer_id": "cus_test",
                "stripe_subscription_id": "sub_test_123",
                "plan_tier": "starter",
            }
        )
        mock_repo.set_overage_enabled = AsyncMock(return_value={})
        mock_stripe.Subscription.retrieve.return_value = {
            "items": {
                "data": [
                    {"id": "si_fixed", "price": {"id": "price_starter"}},
                    {"id": "si_metered", "price": {"id": "price_metered_test"}},
                ]
            }
        }

        response = await async_client.put(
            "/api/v1/billing/overage",
            json={"enabled": True, "limit_dollars": 100.0},
        )
        assert response.status_code == 200

        # No Stripe modify call — already in desired state
        mock_stripe.Subscription.modify.assert_not_called()
        # DynamoDB still updated with the new limit
        mock_repo.set_overage_enabled.assert_called_once_with("user_test_123", True, overage_limit=100_000_000)

    @pytest.mark.asyncio
    @patch("routers.billing.billing_repo")
    @patch("core.services.billing_service.METERED_PRICE_ID", "price_metered_test")
    @patch("core.services.billing_service.stripe")
    async def test_toggle_overage_400_when_no_active_subscription(self, mock_stripe, mock_repo, async_client):
        """Toggling overage on a free-tier (or canceled) account must 400 —
        you can't have overage without a subscription to attach it to."""
        mock_repo.get_by_owner_id = AsyncMock(
            return_value={
                "owner_id": "user_test_123",
                "stripe_customer_id": "cus_test",
                "stripe_subscription_id": None,  # ← no active sub
                "plan_tier": "free",
            }
        )
        mock_repo.set_overage_enabled = AsyncMock(return_value={})

        response = await async_client.put(
            "/api/v1/billing/overage",
            json={"enabled": True},
        )
        assert response.status_code == 400

        # Neither Stripe nor the DB was touched after the validation failed
        mock_stripe.Subscription.modify.assert_not_called()
        mock_repo.set_overage_enabled.assert_not_called()

    @pytest.mark.asyncio
    @patch("routers.billing.billing_repo")
    async def test_toggle_overage_not_found(self, mock_repo, async_client):
        """Should return 404 when no billing account."""
        mock_repo.get_by_owner_id = AsyncMock(return_value=None)

        response = await async_client.put(
            "/api/v1/billing/overage",
            json={"enabled": True},
        )
        assert response.status_code == 404


class TestStripeWebhook:
    """Test POST /api/v1/billing/webhooks/stripe."""

    @pytest.mark.asyncio
    @patch("routers.billing._check_webhook_dedup", new_callable=AsyncMock, return_value=False)
    @patch("routers.billing.billing_repo")
    @patch("routers.billing.stripe")
    async def test_subscription_created_webhook(self, mock_stripe, mock_repo, mock_dedup, async_client):
        """Should update billing account on subscription.created — NO container provisioning."""
        mock_stripe.Webhook.construct_event.return_value = {
            "id": "evt_test_1",
            "type": "customer.subscription.created",
            "data": {
                "object": {
                    "id": "sub_test_123",
                    "customer": "cus_webhook_test",
                    "metadata": {"plan_tier": "starter"},
                }
            },
        }

        mock_repo.get_by_stripe_customer_id = AsyncMock(
            return_value={
                "owner_id": "user_webhook_test",
                "stripe_customer_id": "cus_webhook_test",
                "plan_tier": "free",
            }
        )
        mock_repo.update_subscription = AsyncMock(return_value={})

        with patch("routers.billing.BillingService") as mock_billing_cls:
            mock_billing_svc = AsyncMock()
            mock_billing_cls.return_value = mock_billing_svc

            response = await async_client.post(
                "/api/v1/billing/webhooks/stripe",
                content=b'{"test": true}',
                headers={
                    "stripe-signature": "test_sig",
                    "content-type": "application/json",
                },
            )
        assert response.status_code == 200
        mock_billing_svc.update_subscription.assert_called_once()

    @pytest.mark.asyncio
    @patch("routers.billing._check_webhook_dedup", new_callable=AsyncMock, return_value=False)
    @patch("routers.billing.billing_repo")
    @patch("routers.billing.stripe")
    async def test_subscription_deleted_webhook(self, mock_stripe, mock_repo, mock_dedup, async_client):
        """Should cancel subscription and disable overage — NO container stop."""
        mock_stripe.Webhook.construct_event.return_value = {
            "id": "evt_test_2",
            "type": "customer.subscription.deleted",
            "data": {
                "object": {
                    "id": "sub_test_123",
                    "customer": "cus_webhook_test",
                }
            },
        }

        mock_repo.get_by_stripe_customer_id = AsyncMock(
            return_value={
                "owner_id": "user_webhook_test",
                "stripe_customer_id": "cus_webhook_test",
                "plan_tier": "starter",
            }
        )

        with patch("routers.billing.BillingService") as mock_billing_cls:
            mock_billing_svc = AsyncMock()
            mock_billing_cls.return_value = mock_billing_svc

            response = await async_client.post(
                "/api/v1/billing/webhooks/stripe",
                content=b'{"test": true}',
                headers={
                    "stripe-signature": "test_sig",
                    "content-type": "application/json",
                },
            )
        assert response.status_code == 200
        mock_billing_svc.cancel_subscription.assert_called_once()

    @pytest.mark.asyncio
    @patch("routers.billing.stripe")
    async def test_webhook_invalid_signature(self, mock_stripe, async_client):
        """Should return 400 on invalid signature."""
        mock_stripe.Webhook.construct_event.side_effect = Exception("bad sig")

        response = await async_client.post(
            "/api/v1/billing/webhooks/stripe",
            content=b'{"test": true}',
            headers={
                "stripe-signature": "bad_sig",
                "content-type": "application/json",
            },
        )
        assert response.status_code == 400
