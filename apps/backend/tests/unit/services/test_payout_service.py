"""Tests for payout_service Stripe Connect Express scaffold."""

import os

# Match codebase pattern: seed CLERK_ISSUER before any core.* import.
os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")

from unittest.mock import MagicMock, patch  # noqa: E402

import pytest  # noqa: E402

from core.services import payout_service  # noqa: E402


@pytest.mark.asyncio
@patch("core.services.payout_service.stripe")
async def test_create_connect_account_for_seller(mock_stripe):
    mock_stripe.Account.create.return_value = MagicMock(id="acct_test_123")
    result = await payout_service.create_connect_account(
        seller_id="user_abc",
        email="seller@example.com",
        country="US",
    )
    assert result == "acct_test_123"
    mock_stripe.Account.create.assert_called_once()
    call_kwargs = mock_stripe.Account.create.call_args.kwargs
    assert call_kwargs["type"] == "express"
    assert call_kwargs["country"] == "US"
    assert call_kwargs["email"] == "seller@example.com"
    assert call_kwargs["metadata"]["seller_id"] == "user_abc"
    assert "idempotency_key" in call_kwargs


@pytest.mark.asyncio
@patch("core.services.payout_service.stripe")
async def test_create_onboarding_link(mock_stripe):
    mock_stripe.AccountLink.create.return_value = MagicMock(url="https://connect.stripe.com/setup/abc123")
    url = await payout_service.create_onboarding_link(
        connect_account_id="acct_test_123",
        refresh_url="https://example.com/refresh",
        return_url="https://example.com/return",
    )
    assert url == "https://connect.stripe.com/setup/abc123"
    call_kwargs = mock_stripe.AccountLink.create.call_args.kwargs
    assert call_kwargs["account"] == "acct_test_123"
    assert call_kwargs["type"] == "account_onboarding"


@pytest.mark.asyncio
@patch("core.services.payout_service.stripe")
async def test_rejects_non_us_country(mock_stripe):
    """Per design doc, v1 = US sellers only."""
    with pytest.raises(payout_service.UnsupportedCountryError):
        await payout_service.create_connect_account(
            seller_id="user_abc",
            email="seller@example.com",
            country="DE",
        )
    mock_stripe.Account.create.assert_not_called()
