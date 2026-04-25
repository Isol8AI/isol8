"""When Clerk fires user.updated with a new email, push it to Stripe Customer."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_user_updated_with_new_email_pushes_to_stripe(async_client, monkeypatch):
    fake_account = {
        "owner_id": "u_1",
        "stripe_customer_id": "cus_existing",
    }

    payload = {
        "type": "user.updated",
        "data": {
            "id": "u_1",
            "email_addresses": [{"id": "ea_1", "email_address": "new@example.com"}],
            "primary_email_address_id": "ea_1",
        },
    }

    # Bypass the handler's svix HMAC signature check — we're testing the
    # downstream sync, not signature verification.
    monkeypatch.setattr(
        "routers.webhooks._verify_svix_signature",
        lambda body, headers: None,
    )

    with (
        patch(
            "core.repositories.billing_repo.get_by_owner_id",
            new=AsyncMock(return_value=fake_account),
        ),
        patch("stripe.Customer.modify") as mock_stripe_modify,
    ):
        resp = await async_client.post(
            "/api/v1/webhooks/clerk",
            json=payload,
            headers={
                "svix-id": "msg_test",
                "svix-timestamp": "1234567890",
                "svix-signature": "ignored",
            },
        )

    assert resp.status_code == 200
    mock_stripe_modify.assert_called_once_with(
        "cus_existing",
        email="new@example.com",
        idempotency_key="customer_email_sync:u_1:new@example.com",
    )


@pytest.mark.asyncio
async def test_user_updated_without_stripe_customer_skips_sync(async_client, monkeypatch):
    """If the user has no Stripe customer yet, don't try to push email."""
    payload = {
        "type": "user.updated",
        "data": {
            "id": "u_1",
            "email_addresses": [{"id": "ea_1", "email_address": "x@y.com"}],
            "primary_email_address_id": "ea_1",
        },
    }
    monkeypatch.setattr(
        "routers.webhooks._verify_svix_signature",
        lambda body, headers: None,
    )

    with (
        patch(
            "core.repositories.billing_repo.get_by_owner_id",
            new=AsyncMock(return_value=None),
        ),
        patch("stripe.Customer.modify") as mock_stripe_modify,
    ):
        resp = await async_client.post(
            "/api/v1/webhooks/clerk",
            json=payload,
            headers={
                "svix-id": "msg_test",
                "svix-timestamp": "1234567890",
                "svix-signature": "ignored",
            },
        )

    assert resp.status_code == 200
    mock_stripe_modify.assert_not_called()
