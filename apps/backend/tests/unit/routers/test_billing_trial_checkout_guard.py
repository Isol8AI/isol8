"""Tests for the trial-checkout 409 guard (audit C3).

The original guard only blocked re-checkout when status was in
``{"active", "trialing", "past_due"}``. That left the door open for
trial gaming via cancel + restart: a user could complete a 14-day
trial, cancel before day 15 (no $50 charge), then immediately call
``POST /billing/trial-checkout`` again to start a fresh trial. Net
effect: unlimited free trials => unlimited always-on ECS Fargate cost
to us.

These tests pin down the expanded blocklist.
"""

from unittest.mock import AsyncMock, patch

import pytest


_BLOCKED_LOCAL_STATUSES = [
    "active",
    "trialing",
    "past_due",
    "canceled",
    "incomplete",
    "incomplete_expired",
    "unpaid",
    "paused",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked_status", _BLOCKED_LOCAL_STATUSES)
@patch("routers.billing.billing_repo")
async def test_trial_checkout_409s_on_blocked_local_status(mock_repo, blocked_status, async_client):
    """Local subscription_status in any blocked state -> 409, no
    new Checkout session created."""
    mock_repo.get_by_owner_id = AsyncMock(
        return_value={
            "owner_id": "user_test_123",
            "stripe_customer_id": "cus_X",
            "stripe_subscription_id": "sub_X",
            "subscription_status": blocked_status,
        }
    )

    resp = await async_client.post(
        "/api/v1/billing/trial-checkout",
        json={"provider_choice": "bedrock_claude"},
    )
    assert resp.status_code == 409, f"status={blocked_status} should be blocked but got {resp.status_code}"
    assert resp.json()["detail"].startswith("already_subscribed:")


@pytest.mark.asyncio
@patch("core.services.billing_service.create_flat_fee_checkout")
@patch("routers.billing.stripe.Subscription.retrieve")
@patch("routers.billing.billing_repo")
async def test_trial_checkout_409s_when_live_stripe_status_is_canceled(
    mock_repo, mock_retrieve, mock_create_checkout, async_client
):
    """Local row missing subscription_status but legacy stripe_subscription_id
    is set; live Stripe call returns ``canceled`` -> 409.

    Pre-fix this fell through and minted a NEW subscription, which is
    the trial-gaming exploit.
    """
    mock_repo.get_by_owner_id = AsyncMock(
        return_value={
            "owner_id": "user_test_123",
            "stripe_customer_id": "cus_X",
            "stripe_subscription_id": "sub_X",
            "subscription_status": None,  # local row not backfilled
        }
    )
    mock_retrieve.return_value = {"status": "canceled"}

    resp = await async_client.post(
        "/api/v1/billing/trial-checkout",
        json={"provider_choice": "bedrock_claude"},
    )
    assert resp.status_code == 409
    mock_create_checkout.assert_not_called()
