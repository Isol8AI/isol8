"""Confirm Stripe Customer.create runs WITHOUT a stable idempotency_key.

Customer creation is now keyed by email — ``stripe.Customer.list(email=...)``
finds existing customers before falling back to ``Customer.create``. This
also resolves issue #417 (the dead-id wedge from out-of-band deletes): a
deleted customer simply doesn't appear in the email list anymore, so the
next call creates a fresh one rather than reusing the dead id.

Even on the create-path, ``idempotency_key`` is deliberately omitted so a
24h Stripe cache can't pin a dead customer id.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
@patch("core.services.billing_service.billing_repo")
@patch("core.services.billing_service.stripe")
async def test_create_customer_does_not_pass_stable_idempotency_key(mock_stripe, mock_repo):
    """BillingService.create_customer_for_owner must NOT pass a stable
    idempotency_key keyed on owner_id to stripe.Customer.create.

    A stable key collides with Stripe's 24h cache: if the customer is
    deleted out-of-band (dashboard cleanup, dev reset), Stripe keeps
    returning the dead id for ~24h and every downstream checkout 400s
    with `No such customer`. Issue #417 documents the recurring impact.
    """
    from core.services.billing_service import BillingService

    mock_repo.get_by_owner_id = AsyncMock(return_value=None)
    # No existing email match → falls through to Customer.create.
    mock_stripe.Customer.list.return_value = MagicMock(data=[])
    mock_stripe.Customer.create.return_value = MagicMock(id="cus_test")
    mock_repo.create_if_not_exists = AsyncMock(
        return_value={
            "owner_id": "u_1",
            "stripe_customer_id": "cus_test",
            "plan_tier": "free",
        }
    )

    await BillingService().create_customer_for_owner(owner_id="u_1", email="x@y.com")

    _, kwargs = mock_stripe.Customer.create.call_args
    key = kwargs.get("idempotency_key")
    assert key is None or "owner_id" not in str(key) and "u_1" not in str(key), (
        f"Customer.create should not receive a stable owner-keyed idempotency_key, "
        f"got idempotency_key={key!r}. Email-keyed lookup is the canonical dedupe."
    )
