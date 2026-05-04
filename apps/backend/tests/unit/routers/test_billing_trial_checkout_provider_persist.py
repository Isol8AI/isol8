"""Workstream B race-fix tests for /trial-checkout (Task 3 of provider-choice-per-owner).

The /trial-checkout endpoint must synchronously persist provider_choice on
billing_accounts BEFORE creating the Stripe Checkout session. Without that
write, there's a race window between Checkout completion and the
customer.subscription.created webhook landing (async, can be
seconds-to-minutes) where the user lands on /chat and triggers
/container/provision, and provision reads billing.provider_choice and finds
nothing.

These tests pin down:
  1. provider_choice (no byo_provider) is persisted before the Stripe call
  2. byo_provider is persisted alongside provider_choice when byo_key
  3. byo_key without byo_provider 400s before any DDB write
"""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_trial_checkout_persists_provider_choice_synchronously(async_client):
    """Workstream B race-fix: /trial-checkout must write provider_choice
    to billing_accounts BEFORE creating the Stripe Checkout session, so
    /container/provision can read it without waiting for the async webhook.
    """
    fake_account = {
        "owner_id": "user_x",
        "owner_type": "personal",
        "stripe_customer_id": "cus_abc",
    }

    with (
        patch("routers.billing._get_billing_account", new_callable=AsyncMock, return_value=fake_account),
        patch("routers.billing.billing_repo.set_provider_choice", new_callable=AsyncMock) as mock_set_pc,
        patch(
            "core.services.billing_service.create_flat_fee_checkout",
            new_callable=AsyncMock,
        ) as mock_checkout,
    ):
        mock_checkout.return_value = type("S", (), {"url": "https://checkout.stripe.com/foo"})()

        resp = await async_client.post(
            "/api/v1/billing/trial-checkout",
            json={"provider_choice": "bedrock_claude"},
        )

    assert resp.status_code == 200
    mock_set_pc.assert_awaited_once_with(
        "user_x",
        provider_choice="bedrock_claude",
        byo_provider=None,
        owner_type="personal",
    )


@pytest.mark.asyncio
async def test_trial_checkout_persists_byo_provider_when_byo_key(async_client):
    fake_account = {
        "owner_id": "user_y",
        "owner_type": "personal",
        "stripe_customer_id": "cus_def",
    }

    with (
        patch("routers.billing._get_billing_account", new_callable=AsyncMock, return_value=fake_account),
        patch("routers.billing.billing_repo.set_provider_choice", new_callable=AsyncMock) as mock_set_pc,
        patch(
            "core.services.billing_service.create_flat_fee_checkout",
            new_callable=AsyncMock,
        ) as mock_checkout,
    ):
        mock_checkout.return_value = type("S", (), {"url": "https://checkout.stripe.com/foo"})()

        resp = await async_client.post(
            "/api/v1/billing/trial-checkout",
            json={"provider_choice": "byo_key", "byo_provider": "openai"},
        )

    assert resp.status_code == 200
    mock_set_pc.assert_awaited_once_with(
        "user_y",
        provider_choice="byo_key",
        byo_provider="openai",
        owner_type="personal",
    )


@pytest.mark.asyncio
async def test_trial_checkout_byo_key_without_provider_rejected(async_client):
    """If provider_choice=byo_key, byo_provider is required (400 before any DDB write)."""
    with patch(
        "routers.billing.billing_repo.set_provider_choice",
        new_callable=AsyncMock,
    ) as mock_set_pc:
        resp = await async_client.post(
            "/api/v1/billing/trial-checkout",
            json={"provider_choice": "byo_key"},  # missing byo_provider
        )

    assert resp.status_code == 400
    assert "byo_provider" in resp.json().get("detail", "")
    mock_set_pc.assert_not_awaited()
