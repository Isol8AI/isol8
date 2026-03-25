"""Tests for billing API endpoints."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestGetBillingAccount:
    """Test GET /api/v1/billing/account."""

    @pytest.mark.asyncio
    @patch("routers.billing.billing_repo")
    async def test_get_billing_account(self, mock_repo, async_client):
        """Should return billing account for authenticated user."""
        mock_repo.get_by_owner_id = AsyncMock(
            return_value={
                "owner_id": "user_test_123",
                "stripe_customer_id": "cus_billing_test",
                "plan_tier": "free",
                "stripe_subscription_id": None,
            }
        )

        response = await async_client.get("/api/v1/billing/account")
        assert response.status_code == 200
        data = response.json()
        assert data["plan_tier"] == "free"
        assert "current_period" in data

    @pytest.mark.asyncio
    @patch("routers.billing.billing_repo")
    @patch("core.services.billing_service.stripe")
    @patch("core.services.billing_service.billing_repo")
    async def test_get_billing_account_auto_creates(self, mock_svc_repo, mock_stripe, mock_router_repo, async_client):
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
        response = await async_client.get("/api/v1/billing/account")
        assert response.status_code == 200
        data = response.json()
        assert data["plan_tier"] == "free"
        assert data["has_subscription"] is False


class TestGetUsage:
    """Test GET /api/v1/billing/usage."""

    @pytest.mark.asyncio
    @patch("routers.billing.billing_repo")
    async def test_get_usage_empty(self, mock_repo, async_client):
        """Should return empty usage for new account."""
        mock_repo.get_by_owner_id = AsyncMock(
            return_value={
                "owner_id": "user_test_123",
                "stripe_customer_id": "cus_usage_endpoint",
                "plan_tier": "free",
                "stripe_subscription_id": None,
            }
        )

        response = await async_client.get("/api/v1/billing/usage")
        assert response.status_code == 200
        data = response.json()
        assert data["total_cost"] == 0
        assert data["total_requests"] == 0


class TestCheckout:
    """Test POST /api/v1/billing/checkout."""

    @pytest.mark.asyncio
    @patch("routers.billing.billing_repo")
    @patch(
        "core.services.billing_service.PLAN_PRICES", {"starter": {"fixed": "price_starter", "metered": "price_metered"}}
    )
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


class TestStripeWebhook:
    """Test POST /api/v1/billing/webhooks/stripe."""

    @pytest.mark.asyncio
    @patch("routers.billing.billing_repo")
    @patch("routers.billing.get_ecs_manager")
    @patch("routers.billing.stripe")
    async def test_subscription_created_webhook(self, mock_stripe, mock_get_ecs, mock_repo, async_client):
        """Should update billing account and provision ECS service on subscription.created."""
        mock_stripe.Webhook.construct_event.return_value = {
            "type": "customer.subscription.created",
            "data": {
                "object": {
                    "id": "sub_test_123",
                    "customer": "cus_webhook_test",
                    "items": {"data": [{"price": {"lookup_key": "starter_fixed"}}]},
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

        # Mock BillingService.update_subscription
        with patch("routers.billing.BillingService") as mock_billing_cls:
            mock_billing_svc = AsyncMock()
            mock_billing_cls.return_value = mock_billing_svc

            # Mock ECS manager
            mock_ecs = AsyncMock()
            mock_ecs.provision_user_container = AsyncMock(return_value="openclaw-user_web")
            mock_get_ecs.return_value = mock_ecs

            response = await async_client.post(
                "/api/v1/billing/webhooks/stripe",
                content=b'{"test": true}',
                headers={
                    "stripe-signature": "test_sig",
                    "content-type": "application/json",
                },
            )
        assert response.status_code == 200

        # Verify ECS provisioning was called
        mock_ecs.provision_user_container.assert_called_once()

    @pytest.mark.asyncio
    @patch("routers.billing.billing_repo")
    @patch("routers.billing.get_ecs_manager")
    @patch("routers.billing.stripe")
    async def test_subscription_deleted_webhook(self, mock_stripe, mock_get_ecs, mock_repo, async_client):
        """Should cancel subscription and stop ECS service on subscription.deleted."""
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

            mock_ecs = AsyncMock()
            mock_get_ecs.return_value = mock_ecs

            response = await async_client.post(
                "/api/v1/billing/webhooks/stripe",
                content=b'{"test": true}',
                headers={
                    "stripe-signature": "test_sig",
                    "content-type": "application/json",
                },
            )
        assert response.status_code == 200

        # Verify ECS stop was called
        mock_ecs.stop_user_service.assert_called_once()
