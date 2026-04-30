"""Confirm Stripe Customer.create runs WITHOUT a stable idempotency_key.

Every other Stripe write site uses an idempotency_key (delete_customer,
checkout, portal, sub_modify, sub_cancel, balance_tx, invoice_pay), but
Customer.create deliberately does not — the DDB conditional write is the
canonical dedupe. See issue #417 for the wedge-on-out-of-band-delete
incident that drove this.
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
        f"got idempotency_key={key!r}. The DDB conditional write is the canonical dedupe."
    )
