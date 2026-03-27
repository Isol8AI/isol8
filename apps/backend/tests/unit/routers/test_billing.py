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
        assert data["lifetime_spend"] == 5.0
        assert data["within_included"] is True

    @pytest.mark.asyncio
    @patch("routers.billing.usage_repo")
    @patch("routers.billing.check_budget")
    @patch("routers.billing.billing_repo")
    @patch("core.services.billing_service.stripe")
    @patch("core.services.billing_service.billing_repo")
    async def test_get_billing_account_auto_creates(
        self, mock_svc_repo, mock_stripe, mock_router_repo, mock_check_budget, mock_usage_repo, async_client
    ):
        """Should auto-create billing account when none exists."""
        mock_router_repo.get_by_owner_id = AsyncMock(return_value=None)
        mock_stripe.Customer.create.return_value = MagicMock(id="cus_auto_created")
        mock_svc_repo.get_by_owner_id = AsyncMock(return_value=None)
        mock_svc_repo.get_or_create = AsyncMock(
            return_value={
                "owner_id": "user_test_123",
                "stripe_customer_id": "cus_auto_created",
                "plan_tier": "free",
                "stripe_subscription_id": None,
            }
        )
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


class TestGetPricing:
    """Test GET /api/v1/billing/pricing."""

    @pytest.mark.asyncio
    @patch("routers.billing.get_all_prices")
    @patch("routers.billing.billing_repo")
    async def test_get_pricing(self, mock_repo, mock_get_prices, async_client):
        """Should return model pricing with markup."""
        mock_repo.get_by_owner_id = AsyncMock(return_value={"owner_id": "user_test_123", "plan_tier": "free"})
        mock_get_prices.return_value = {
            "minimax.minimax-m2.1": {
                "input": 0.30e-6,
                "output": 1.20e-6,
                "cache_read": 0.0,
                "cache_write": 0.0,
            }
        }

        response = await async_client.get("/api/v1/billing/pricing")
        assert response.status_code == 200
        data = response.json()
        assert "minimax.minimax-m2.1" in data["models"]
        assert data["markup"] == 1.4
        assert data["tier_model"] is not None


class TestCheckout:
    """Test POST /api/v1/billing/checkout."""

    @pytest.mark.asyncio
    @patch("routers.billing.billing_repo")
    @patch("core.services.billing_service.TIER_PRICES", {"starter": "price_starter"})
    @patch("core.services.billing_service.stripe")
    async def test_create_checkout(self, mock_stripe, mock_repo, async_client):
        """Should return Stripe checkout URL."""
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


class TestOverageToggle:
    """Test PUT /api/v1/billing/overage."""

    @pytest.mark.asyncio
    @patch("routers.billing.billing_repo")
    async def test_toggle_overage_on(self, mock_repo, async_client):
        """Should enable overage with limit."""
        mock_repo.get_by_owner_id = AsyncMock(
            return_value={
                "owner_id": "user_test_123",
                "stripe_customer_id": "cus_test",
                "plan_tier": "starter",
            }
        )
        mock_repo.set_overage_enabled = AsyncMock(return_value={})

        response = await async_client.put(
            "/api/v1/billing/overage",
            json={"enabled": True, "limit_dollars": 50.0},
        )
        assert response.status_code == 200
        mock_repo.set_overage_enabled.assert_called_once_with("user_test_123", True, overage_limit=50_000_000)

    @pytest.mark.asyncio
    @patch("routers.billing.billing_repo")
    async def test_toggle_overage_off(self, mock_repo, async_client):
        """Should disable overage."""
        mock_repo.get_by_owner_id = AsyncMock(
            return_value={
                "owner_id": "user_test_123",
                "stripe_customer_id": "cus_test",
                "plan_tier": "starter",
            }
        )
        mock_repo.set_overage_enabled = AsyncMock(return_value={})

        response = await async_client.put(
            "/api/v1/billing/overage",
            json={"enabled": False},
        )
        assert response.status_code == 200
        mock_repo.set_overage_enabled.assert_called_once_with("user_test_123", False, overage_limit=None)

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
    @patch("routers.billing.billing_repo")
    @patch("routers.billing.stripe")
    async def test_subscription_created_webhook(self, mock_stripe, mock_repo, async_client):
        """Should update billing account on subscription.created — NO container provisioning."""
        mock_stripe.Webhook.construct_event.return_value = {
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
    @patch("routers.billing.billing_repo")
    @patch("routers.billing.stripe")
    async def test_subscription_deleted_webhook(self, mock_stripe, mock_repo, async_client):
        """Should cancel subscription and disable overage — NO container stop."""
        mock_stripe.Webhook.construct_event.return_value = {
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
