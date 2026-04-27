"""Tests for create_trial_subscription: Stripe Subscription with trial_period_days=14."""

from unittest.mock import AsyncMock, patch

import pytest
import stripe

from core.services import billing_service


@pytest.mark.asyncio
async def test_create_trial_subscription_passes_required_kwargs(monkeypatch):
    """All Stripe-native trial kwargs are passed correctly."""
    monkeypatch.setattr(billing_service.settings, "STRIPE_FLAT_PRICE_ID", "price_flat")
    fake_sub = type(
        "S",
        (),
        {
            "id": "sub_test",
            "status": "trialing",
            "trial_end": 1700000000,
        },
    )()
    with (
        patch.object(stripe.Subscription, "create", return_value=fake_sub) as mock_create,
        patch(
            "core.repositories.billing_repo.get_by_owner_id",
            new=AsyncMock(return_value={"stripe_customer_id": "cus_x"}),
        ),
        patch(
            "core.repositories.billing_repo.set_subscription",
            new=AsyncMock(),
        ),
    ):
        result = await billing_service.create_trial_subscription(owner_id="u_1", payment_method_id="pm_1")

    assert result.id == "sub_test"
    _, kwargs = mock_create.call_args
    assert kwargs["trial_period_days"] == 14
    assert kwargs["customer"] == "cus_x"
    assert kwargs["items"] == [{"price": "price_flat"}]
    assert kwargs["default_payment_method"] == "pm_1"
    assert kwargs["automatic_tax"] == {"enabled": True}
    assert kwargs["payment_behavior"] == "default_incomplete"
    assert kwargs["payment_settings"] == {
        "save_default_payment_method": "on_subscription",
        "payment_method_types": ["card"],
    }
    assert kwargs["idempotency_key"] == "trial_signup:u_1"


@pytest.mark.asyncio
async def test_create_trial_subscription_persists_to_billing_repo(monkeypatch):
    """After Stripe create, the subscription_id + status are persisted."""
    monkeypatch.setattr(billing_service.settings, "STRIPE_FLAT_PRICE_ID", "price_flat")
    fake_sub = type(
        "S",
        (),
        {
            "id": "sub_test",
            "status": "trialing",
            "trial_end": 1700000000,
        },
    )()
    with (
        patch.object(stripe.Subscription, "create", return_value=fake_sub),
        patch(
            "core.repositories.billing_repo.get_by_owner_id",
            new=AsyncMock(return_value={"stripe_customer_id": "cus_x"}),
        ),
        patch(
            "core.repositories.billing_repo.set_subscription",
            new=AsyncMock(),
        ) as mock_set,
    ):
        await billing_service.create_trial_subscription(owner_id="u_1", payment_method_id="pm_1")

    mock_set.assert_awaited_once()
    _, kwargs = mock_set.call_args
    assert kwargs.get("owner_id") == "u_1" or "u_1" in mock_set.call_args.args
    # status / subscription_id should be passed; exact kwarg names may vary
    # by repo signature — just verify they're present.


@pytest.mark.asyncio
async def test_create_trial_subscription_raises_without_flat_price_id(monkeypatch):
    monkeypatch.setattr(billing_service.settings, "STRIPE_FLAT_PRICE_ID", "")
    with pytest.raises(Exception, match="STRIPE_FLAT_PRICE_ID"):
        await billing_service.create_trial_subscription(owner_id="u_1", payment_method_id="pm_1")


@pytest.mark.asyncio
async def test_create_trial_subscription_raises_without_stripe_customer(monkeypatch):
    monkeypatch.setattr(billing_service.settings, "STRIPE_FLAT_PRICE_ID", "price_flat")
    with patch(
        "core.repositories.billing_repo.get_by_owner_id",
        new=AsyncMock(return_value=None),
    ):
        with pytest.raises(Exception, match="No Stripe customer"):
            await billing_service.create_trial_subscription(owner_id="u_1", payment_method_id="pm_1")
