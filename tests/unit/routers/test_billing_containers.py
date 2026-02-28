"""
Tests for container provisioning integration with billing.

TDD: Tests written BEFORE implementation.
Tests that Stripe webhook events trigger container lifecycle operations.
"""

import pytest
from unittest.mock import MagicMock, patch

from models.billing import BillingAccount


class TestSubscriptionCreatedProvisionContainer:
    """Test that subscription.created provisions a container."""

    @pytest.fixture
    async def billing_account(self, db_session):
        account = BillingAccount(
            clerk_user_id="user_test_123",
            stripe_customer_id="cus_provision_test",
        )
        db_session.add(account)
        await db_session.commit()
        return account

    @pytest.mark.asyncio
    @patch("routers.billing.get_container_manager")
    @patch("routers.billing.stripe")
    async def test_subscription_created_provisions_container(
        self, mock_stripe, mock_get_cm, async_client, billing_account, db_session
    ):
        """subscription.created event triggers container provisioning."""
        mock_cm = MagicMock()
        mock_cm.provision_container.return_value = MagicMock(
            user_id="user_test_123", port=19000, container_id="abc123", status="running", gateway_token="test-gw-token"
        )
        mock_get_cm.return_value = mock_cm

        mock_stripe.Webhook.construct_event.return_value = {
            "type": "customer.subscription.created",
            "data": {
                "object": {
                    "id": "sub_test_provision",
                    "customer": "cus_provision_test",
                    "items": {"data": [{"price": {"lookup_key": "starter_fixed"}}]},
                    "metadata": {"plan_tier": "starter"},
                }
            },
        }

        response = await async_client.post(
            "/api/v1/billing/webhooks/stripe",
            content=b'{"test": true}',
            headers={
                "stripe-signature": "test_sig",
                "content-type": "application/json",
            },
        )
        assert response.status_code == 200

        # Container should have been provisioned for the user
        mock_cm.provision_container.assert_called_once_with("user_test_123")

    @pytest.mark.asyncio
    @patch("routers.billing.get_container_manager")
    @patch("routers.billing.stripe")
    async def test_subscription_created_free_tier_no_provision(
        self, mock_stripe, mock_get_cm, async_client, billing_account, db_session
    ):
        """Free tier subscription does NOT provision a container."""
        mock_cm = MagicMock()
        mock_get_cm.return_value = mock_cm

        mock_stripe.Webhook.construct_event.return_value = {
            "type": "customer.subscription.created",
            "data": {
                "object": {
                    "id": "sub_free",
                    "customer": "cus_provision_test",
                    "items": {"data": []},
                    "metadata": {"plan_tier": "free"},
                }
            },
        }

        response = await async_client.post(
            "/api/v1/billing/webhooks/stripe",
            content=b'{"test": true}',
            headers={
                "stripe-signature": "test_sig",
                "content-type": "application/json",
            },
        )
        assert response.status_code == 200

        # Free tier should NOT provision a container
        mock_cm.provision_container.assert_not_called()


class TestSubscriptionDeletedStopContainer:
    """Test that subscription.deleted stops a container."""

    @pytest.fixture
    async def billing_account(self, db_session):
        account = BillingAccount(
            clerk_user_id="user_test_123",
            stripe_customer_id="cus_cancel_test",
            plan_tier="starter",
            stripe_subscription_id="sub_active_123",
        )
        db_session.add(account)
        await db_session.commit()
        return account

    @pytest.mark.asyncio
    @patch("routers.billing.get_container_manager")
    @patch("routers.billing.stripe")
    async def test_subscription_deleted_stops_container(
        self, mock_stripe, mock_get_cm, async_client, billing_account, db_session
    ):
        """subscription.deleted event stops the user's container."""
        mock_cm = MagicMock()
        mock_cm.stop_container.return_value = True
        mock_get_cm.return_value = mock_cm

        mock_stripe.Webhook.construct_event.return_value = {
            "type": "customer.subscription.deleted",
            "data": {
                "object": {
                    "id": "sub_active_123",
                    "customer": "cus_cancel_test",
                }
            },
        }

        response = await async_client.post(
            "/api/v1/billing/webhooks/stripe",
            content=b'{"test": true}',
            headers={
                "stripe-signature": "test_sig",
                "content-type": "application/json",
            },
        )
        assert response.status_code == 200

        # Container should be stopped (not removed — volume preserved)
        mock_cm.stop_container.assert_called_once_with("user_test_123")

    @pytest.mark.asyncio
    @patch("routers.billing.get_container_manager")
    @patch("routers.billing.stripe")
    async def test_subscription_deleted_handles_no_container(
        self, mock_stripe, mock_get_cm, async_client, billing_account, db_session
    ):
        """subscription.deleted handles gracefully when no container exists."""
        mock_cm = MagicMock()
        mock_cm.stop_container.return_value = False  # No container found
        mock_get_cm.return_value = mock_cm

        mock_stripe.Webhook.construct_event.return_value = {
            "type": "customer.subscription.deleted",
            "data": {
                "object": {
                    "id": "sub_active_123",
                    "customer": "cus_cancel_test",
                }
            },
        }

        response = await async_client.post(
            "/api/v1/billing/webhooks/stripe",
            content=b'{"test": true}',
            headers={
                "stripe-signature": "test_sig",
                "content-type": "application/json",
            },
        )
        # Should succeed even if no container to stop
        assert response.status_code == 200


class TestProvisionErrorHandling:
    """Test container provisioning error handling in billing flow."""

    @pytest.fixture
    async def billing_account(self, db_session):
        account = BillingAccount(
            clerk_user_id="user_test_123",
            stripe_customer_id="cus_error_test",
        )
        db_session.add(account)
        await db_session.commit()
        return account

    @pytest.mark.asyncio
    @patch("routers.billing.get_container_manager")
    @patch("routers.billing.stripe")
    async def test_provision_failure_does_not_break_webhook(
        self, mock_stripe, mock_get_cm, async_client, billing_account, db_session
    ):
        """Container provisioning failure doesn't cause webhook to fail."""
        from core.containers.manager import ContainerError

        mock_cm = MagicMock()
        mock_cm.provision_container.side_effect = ContainerError("Docker unavailable")
        mock_get_cm.return_value = mock_cm

        mock_stripe.Webhook.construct_event.return_value = {
            "type": "customer.subscription.created",
            "data": {
                "object": {
                    "id": "sub_fail",
                    "customer": "cus_error_test",
                    "items": {"data": []},
                    "metadata": {"plan_tier": "starter"},
                }
            },
        }

        response = await async_client.post(
            "/api/v1/billing/webhooks/stripe",
            content=b'{"test": true}',
            headers={
                "stripe-signature": "test_sig",
                "content-type": "application/json",
            },
        )
        # Webhook should still succeed — provisioning failure logged, not raised
        assert response.status_code == 200
