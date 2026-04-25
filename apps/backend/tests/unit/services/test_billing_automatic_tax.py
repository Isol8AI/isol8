"""Confirm checkout sessions are created with Stripe Tax enabled."""

from unittest.mock import MagicMock, patch

import pytest

from core.services.billing_service import BillingService


@pytest.fixture
def billing_account():
    return {
        "owner_id": "u_1",
        "stripe_customer_id": "cus_test",
    }


@pytest.fixture
def service():
    return BillingService()


@pytest.mark.asyncio
@patch(
    "core.services.billing_service.TIER_PRICES",
    {"starter": "price_starter"},
)
@patch("core.services.billing_service.stripe")
async def test_create_checkout_passes_automatic_tax_enabled(mock_stripe, service, billing_account):
    """billing_service.create_checkout_session passes
    automatic_tax={'enabled': True} so Stripe collects tax."""
    mock_stripe.checkout.Session.create.return_value = MagicMock(url="https://checkout/x", id="cs_test")

    await service.create_checkout_session(billing_account=billing_account, tier="starter")

    _, kwargs = mock_stripe.checkout.Session.create.call_args
    assert kwargs.get("automatic_tax") == {"enabled": True}, (
        f"Expected automatic_tax={{'enabled': True}}, got {kwargs.get('automatic_tax')!r}"
    )


@pytest.mark.asyncio
@patch(
    "core.services.billing_service.TIER_PRICES",
    {"starter": "price_starter"},
)
@patch("core.services.billing_service.stripe")
async def test_create_checkout_passes_customer_update_address_auto(mock_stripe, service, billing_account):
    """When automatic_tax is on, Stripe requires customer_update={'address': 'auto'}
    or the API call fails. Verify it's set."""
    mock_stripe.checkout.Session.create.return_value = MagicMock(url="https://checkout/x", id="cs_test")

    await service.create_checkout_session(billing_account=billing_account, tier="starter")

    _, kwargs = mock_stripe.checkout.Session.create.call_args
    assert kwargs.get("customer_update") == {"address": "auto"}, (
        f"Expected customer_update={{'address': 'auto'}}, got {kwargs.get('customer_update')!r}"
    )
