"""Tests for BillingService — flat-fee model."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.services import billing_service
from core.services.billing_service import (
    BillingService,
    BillingServiceError,
)


class TestBillingServiceCreateCustomer:
    """Stripe customer creation with DynamoDB conditional write dedup."""

    @pytest.fixture
    def service(self):
        return BillingService()

    @pytest.mark.asyncio
    @patch("core.services.billing_service.billing_repo")
    @patch("core.services.billing_service.stripe")
    async def test_create_customer_for_owner(self, mock_stripe, mock_repo, service):
        mock_repo.get_by_owner_id = AsyncMock(return_value=None)
        mock_stripe.Customer.create.return_value = MagicMock(id="cus_new_123")
        mock_repo.create_if_not_exists = AsyncMock(
            return_value={
                "owner_id": "user_new_123",
                "stripe_customer_id": "cus_new_123",
            }
        )

        account = await service.create_customer_for_owner(
            owner_id="user_new_123",
            email="test@example.com",
        )

        mock_stripe.Customer.create.assert_called_once()
        assert account["owner_id"] == "user_new_123"
        assert account["stripe_customer_id"] == "cus_new_123"

    @pytest.mark.asyncio
    @patch("core.services.billing_service.billing_repo")
    @patch("core.services.billing_service.stripe")
    async def test_create_customer_race_deletes_orphan(self, mock_stripe, mock_repo, service):
        """If the DDB conditional put loses the race, delete the orphan Stripe customer."""
        from core.repositories.billing_repo import AlreadyExistsError

        # The patch replaces billing_repo with a MagicMock, including its
        # AlreadyExistsError attribute. Restore the real class so the
        # `except billing_repo.AlreadyExistsError` clause in
        # create_customer_for_owner can match.
        mock_repo.AlreadyExistsError = AlreadyExistsError
        mock_repo.get_by_owner_id = AsyncMock(
            side_effect=[
                None,
                {"owner_id": "user_race", "stripe_customer_id": "cus_winner"},
            ]
        )
        mock_stripe.Customer.create.return_value = MagicMock(id="cus_loser")
        mock_repo.create_if_not_exists = AsyncMock(side_effect=AlreadyExistsError("user_race"))

        result = await service.create_customer_for_owner(owner_id="user_race")

        mock_stripe.Customer.delete.assert_called_once()
        delete_args, delete_kwargs = mock_stripe.Customer.delete.call_args
        assert delete_args[0] == "cus_loser"
        assert delete_kwargs.get("idempotency_key") == "delete_customer:cus_loser"
        assert result["stripe_customer_id"] == "cus_winner"

    @pytest.mark.asyncio
    @patch("core.services.billing_service.billing_repo")
    @patch("core.services.billing_service.stripe")
    async def test_create_customer_idempotent(self, mock_stripe, mock_repo, service):
        existing = {
            "owner_id": "user_idem",
            "stripe_customer_id": "cus_idem",
            "id": "acc-123",
        }
        mock_repo.get_by_owner_id = AsyncMock(return_value=existing)

        result = await service.create_customer_for_owner(
            owner_id="user_idem",
            email="idem@example.com",
        )

        assert result["id"] == "acc-123"
        mock_stripe.Customer.create.assert_not_called()


class TestBillingServicePortal:
    @pytest.mark.asyncio
    @patch("core.services.billing_service.stripe")
    async def test_create_portal_session(self, mock_stripe):
        mock_stripe.billing_portal.Session.create.return_value = MagicMock(url="https://billing.stripe.com/test")
        url = await BillingService().create_portal_session(
            billing_account={"owner_id": "user_portal", "stripe_customer_id": "cus_portal"}
        )
        assert url == "https://billing.stripe.com/test"


class TestBillingServiceCancelSubscription:
    """Cancel writes status='canceled' and clears the subscription id via set_subscription."""

    @pytest.mark.asyncio
    @patch("core.services.billing_service.billing_repo")
    async def test_cancel_subscription(self, mock_repo):
        mock_repo.set_subscription = AsyncMock()
        await BillingService().cancel_subscription({"owner_id": "user_sub", "stripe_subscription_id": "sub_123"})
        mock_repo.set_subscription.assert_called_once_with(
            owner_id="user_sub",
            subscription_id=None,
            status="canceled",
            trial_end=None,
        )


class TestCreateFlatFeeCheckout:
    """Tests for the flat-fee Checkout helper used by the post-pivot onboarding
    wizard (single $50/mo price, no per-tier branching)."""

    @pytest.mark.asyncio
    async def test_create_flat_fee_checkout_uses_flat_price_and_tax(self, monkeypatch):
        monkeypatch.setattr(billing_service.settings, "STRIPE_FLAT_PRICE_ID", "price_flat_test")
        fake_session = MagicMock(url="https://checkout/x", id="cs_test")
        with (
            patch.object(billing_service.stripe.checkout.Session, "create", return_value=fake_session) as mock_create,
            patch.object(
                billing_service.billing_repo,
                "get_by_owner_id",
                new=AsyncMock(return_value={"stripe_customer_id": "cus_test"}),
            ),
        ):
            result = await billing_service.create_flat_fee_checkout(owner_id="u_1")

        assert result is fake_session
        _, kwargs = mock_create.call_args
        assert kwargs["line_items"] == [{"price": "price_flat_test", "quantity": 1}]
        assert kwargs["automatic_tax"] == {"enabled": True}
        assert kwargs["customer_update"] == {"address": "auto"}
        assert kwargs["customer"] == "cus_test"
        assert kwargs["mode"] == "subscription"
        assert kwargs["idempotency_key"].startswith("flat_checkout:u_1:")

    @pytest.mark.asyncio
    async def test_create_flat_fee_checkout_raises_without_flat_price_id(self, monkeypatch):
        monkeypatch.setattr(billing_service.settings, "STRIPE_FLAT_PRICE_ID", "")
        with pytest.raises(BillingServiceError, match="STRIPE_FLAT_PRICE_ID not configured"):
            await billing_service.create_flat_fee_checkout(owner_id="u_1")

    @pytest.mark.asyncio
    async def test_create_flat_fee_checkout_raises_without_stripe_customer(self, monkeypatch):
        monkeypatch.setattr(billing_service.settings, "STRIPE_FLAT_PRICE_ID", "price_flat_test")
        with patch.object(
            billing_service.billing_repo,
            "get_by_owner_id",
            new=AsyncMock(return_value=None),
        ):
            with pytest.raises(BillingServiceError, match="No Stripe customer"):
                await billing_service.create_flat_fee_checkout(owner_id="u_missing")
