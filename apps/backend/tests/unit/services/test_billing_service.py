"""Tests for BillingService (DynamoDB-backed) — hybrid tier model."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.services.billing_service import BillingService, BillingServiceError


class TestBillingServiceCreateCustomer:
    """Test Stripe customer creation."""

    @pytest.fixture
    def service(self):
        return BillingService()

    @pytest.mark.asyncio
    @patch("core.services.billing_service.billing_repo")
    @patch("core.services.billing_service.stripe")
    async def test_create_customer_for_owner(self, mock_stripe, mock_repo, service):
        """Should create Stripe customer and billing account for user."""
        mock_repo.get_by_owner_id = AsyncMock(return_value=None)
        mock_stripe.Customer.create.return_value = MagicMock(id="cus_new_123")
        mock_repo.get_or_create = AsyncMock(
            return_value={
                "owner_id": "user_new_123",
                "stripe_customer_id": "cus_new_123",
                "plan_tier": "free",
            }
        )

        account = await service.create_customer_for_owner(
            owner_id="user_new_123",
            email="test@example.com",
        )

        mock_stripe.Customer.create.assert_called_once()
        assert account["owner_id"] == "user_new_123"
        assert account["stripe_customer_id"] == "cus_new_123"
        assert account["plan_tier"] == "free"

    @pytest.mark.asyncio
    @patch("core.services.billing_service.billing_repo")
    @patch("core.services.billing_service.stripe")
    async def test_create_customer_idempotent(self, mock_stripe, mock_repo, service):
        """Should return existing account if already created."""
        existing = {
            "owner_id": "user_idem",
            "stripe_customer_id": "cus_idem",
            "plan_tier": "free",
            "id": "acc-123",
        }
        mock_repo.get_by_owner_id = AsyncMock(return_value=existing)

        result = await service.create_customer_for_owner(
            owner_id="user_idem",
            email="idem@example.com",
        )

        assert result["id"] == "acc-123"
        mock_stripe.Customer.create.assert_not_called()
        mock_repo.get_or_create.assert_not_called()


class TestBillingServiceCheckout:
    """Test Stripe Checkout session creation."""

    @pytest.fixture
    def billing_account(self):
        return {
            "owner_id": "user_checkout",
            "stripe_customer_id": "cus_checkout",
        }

    @pytest.fixture
    def service(self):
        return BillingService()

    @pytest.mark.asyncio
    @patch(
        "core.services.billing_service.TIER_PRICES",
        {"starter": "price_starter"},
    )
    @patch("core.services.billing_service.stripe")
    async def test_create_checkout_session(self, mock_stripe, service, billing_account):
        """Should create Stripe Checkout session."""
        mock_stripe.checkout.Session.create.return_value = MagicMock(url="https://checkout.stripe.com/test")

        url = await service.create_checkout_session(
            billing_account=billing_account,
            tier="starter",
        )

        assert url == "https://checkout.stripe.com/test"
        mock_stripe.checkout.Session.create.assert_called_once()

    @pytest.mark.asyncio
    @patch(
        "core.services.billing_service.TIER_PRICES",
        {"pro": "price_pro"},
    )
    @patch("core.services.billing_service.stripe")
    async def test_checkout_passes_plan_tier_metadata(self, mock_stripe, service, billing_account):
        """Should pass plan_tier metadata so webhook can read the tier."""
        mock_stripe.checkout.Session.create.return_value = MagicMock(url="https://checkout.stripe.com/test")

        await service.create_checkout_session(billing_account=billing_account, tier="pro")

        call_kwargs = mock_stripe.checkout.Session.create.call_args[1]
        assert call_kwargs["subscription_data"]["metadata"]["plan_tier"] == "pro"

    @pytest.mark.asyncio
    async def test_checkout_rejects_unknown_tier(self, service, billing_account):
        """Should raise error for unknown tier."""
        with pytest.raises(BillingServiceError, match="Unknown tier"):
            await service.create_checkout_session(billing_account=billing_account, tier="diamond")


class TestBillingServicePortal:
    """Test Stripe Customer Portal session."""

    @pytest.fixture
    def billing_account(self):
        return {
            "owner_id": "user_portal",
            "stripe_customer_id": "cus_portal",
        }

    @pytest.fixture
    def service(self):
        return BillingService()

    @pytest.mark.asyncio
    @patch("core.services.billing_service.stripe")
    async def test_create_portal_session(self, mock_stripe, service, billing_account):
        """Should create Stripe Portal session."""
        mock_stripe.billing_portal.Session.create.return_value = MagicMock(url="https://billing.stripe.com/test")

        url = await service.create_portal_session(billing_account=billing_account)

        assert url == "https://billing.stripe.com/test"


class TestBillingServiceSubscription:
    """Test subscription management."""

    @pytest.fixture
    def billing_account(self):
        return {
            "owner_id": "user_sub",
            "stripe_customer_id": "cus_sub",
        }

    @pytest.fixture
    def service(self):
        return BillingService()

    @pytest.mark.asyncio
    @patch("core.services.billing_service.billing_repo")
    async def test_update_subscription(self, mock_repo, service, billing_account):
        """Should update billing account with subscription details."""
        mock_repo.update_subscription = AsyncMock(
            return_value={
                "owner_id": "user_sub",
                "stripe_subscription_id": "sub_123",
                "plan_tier": "starter",
            }
        )

        await service.update_subscription(billing_account, "sub_123", "starter")

        mock_repo.update_subscription.assert_called_once_with(
            owner_id="user_sub",
            stripe_subscription_id="sub_123",
            plan_tier="starter",
        )

    @pytest.mark.asyncio
    @patch("core.services.billing_service.billing_repo")
    async def test_cancel_subscription(self, mock_repo, service, billing_account):
        """Should revert to free tier and disable overage on cancellation."""
        mock_repo.update_subscription = AsyncMock(
            return_value={
                "owner_id": "user_sub",
                "stripe_subscription_id": None,
                "plan_tier": "free",
            }
        )
        mock_repo.set_overage_enabled = AsyncMock(return_value={})

        await service.cancel_subscription(billing_account)

        mock_repo.update_subscription.assert_called_once_with(
            owner_id="user_sub",
            stripe_subscription_id=None,
            plan_tier="free",
        )
        mock_repo.set_overage_enabled.assert_called_once_with("user_sub", False)
