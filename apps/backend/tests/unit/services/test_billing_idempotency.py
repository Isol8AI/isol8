"""Confirm the Stripe Customer create site passes an idempotency_key.

One representative test that locks the convention. The other Stripe write
sites in billing_service.py follow the same pattern (see the convention
table in the Stripe Hardening plan / Task 4 prompt):

    Customer.create                       -> create_customer:{owner_id}
    Customer.delete                       -> delete_customer:{customer_id}
    checkout.Session.create               -> checkout:{owner_id}:{5min-bucket}
    billing_portal.Session.create         -> portal:{owner_id}:{5min-bucket}
    Subscription.modify                   -> sub_modify:{sub_id}:<short-op>
    Subscription.delete                   -> sub_cancel:{sub_id}
    Customer.create_balance_transaction   -> balance_tx:{cust_id}:<hash>
    Invoice.pay                           -> invoice_pay:{invoice_id}

Retried HTTP calls (network blip, FastAPI request retry, our own self-heal
logic) must collapse to a single side-effect on Stripe's side rather than
double-creating customers, double-cancelling subs, double-charging cards.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
@patch("core.services.billing_service.billing_repo")
@patch("core.services.billing_service.stripe")
async def test_create_customer_passes_idempotency_key(mock_stripe, mock_repo):
    """BillingService.create_customer_for_owner passes idempotency_key=
    to stripe.Customer.create, derived from the owner_id.

    The key shape `create_customer:{owner_id}` is deterministic so a
    retried HTTP call (e.g. transient network error after the SDK already
    sent the request to Stripe) returns the same Customer instead of
    creating a duplicate.
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
    assert kwargs.get("idempotency_key") == "create_customer:u_1", (
        f"Expected idempotency_key='create_customer:u_1', got {kwargs.get('idempotency_key')!r}"
    )
