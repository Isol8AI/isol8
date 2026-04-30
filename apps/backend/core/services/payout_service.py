"""Payout service: Stripe Connect Express onboarding + Transfer creation.

v1 launches with US sellers only. International support is post-v1.

Connect flow uses 'separate charges and transfers':
  1. Buyer's purchase -> Stripe Charge to the platform balance.
  2. Seller onboards via Express -> Connect account exists.
  3. Held balance flushed via stripe.Transfer.create() to the connected account.

This module owns steps 2 and 3. Step 1 (Charge) lives in marketplace_service
(Plan 2). The webhook handler (also Plan 2) calls back into this module on
account.updated to flush held balances.
"""

from dataclasses import dataclass

import stripe

from core.config import settings


SUPPORTED_COUNTRIES = {"US"}


class UnsupportedCountryError(Exception):
    """Raised when seller's country is not supported in v1."""


async def create_connect_account(*, seller_id: str, email: str, country: str) -> str:
    """Create a Stripe Connect Express account for a seller. Returns account_id.

    Idempotent on seller_id: re-calling for the same seller returns the
    Stripe-side existing account (Stripe deduplicates on idempotency_key).
    """
    if country not in SUPPORTED_COUNTRIES:
        raise UnsupportedCountryError(f"v1 supports only {SUPPORTED_COUNTRIES}; got {country}")

    stripe.api_key = settings.STRIPE_SECRET_KEY
    account = stripe.Account.create(
        type="express",
        country=country,
        email=email,
        capabilities={
            "card_payments": {"requested": True},
            "transfers": {"requested": True},
        },
        metadata={"seller_id": seller_id},
        idempotency_key=f"connect_account_create:{seller_id}",
    )
    return account.id


async def create_onboarding_link(*, connect_account_id: str, refresh_url: str, return_url: str) -> str:
    """Create a one-time Stripe Express onboarding link. Returns the URL."""
    stripe.api_key = settings.STRIPE_SECRET_KEY
    link = stripe.AccountLink.create(
        account=connect_account_id,
        refresh_url=refresh_url,
        return_url=return_url,
        type="account_onboarding",
    )
    return link.url


async def transfer_held_balance(*, connect_account_id: str, amount_cents: int, transfer_group: str) -> str:
    """Create a Transfer from platform balance to the connected account.

    transfer_group: groups Transfers logically per purchase batch; useful for
    Reversals on refund.
    Returns the Stripe transfer_id.
    """
    stripe.api_key = settings.STRIPE_SECRET_KEY
    transfer = stripe.Transfer.create(
        amount=amount_cents,
        currency="usd",
        destination=connect_account_id,
        transfer_group=transfer_group,
        idempotency_key=f"transfer:{connect_account_id}:{transfer_group}",
    )
    return transfer.id


@dataclass
class RefundResult:
    refund_id: str
    reversal_id: str | None


async def refund_purchase(*, charge_id: str, transfer_group: str, full_amount_cents: int) -> RefundResult:
    """Refund a buyer's charge. If a Transfer to the seller has happened,
    reverse it first to claw back the funds.

    Per design doc separate-charges-and-transfers: the original charge is on
    the platform balance. If the seller hasn't received a Transfer yet (still
    in held balance), refund alone is sufficient. If a Transfer has happened,
    we must reverse it before refunding — otherwise the platform eats the cost.

    NOTE: Plan 2 caller (refund router) MUST guard `create_connect_account`
    via a marketplace-payout-accounts DDB lookup before invocation — Stripe's
    24h idempotency window will silently produce a NEW account on day 2 of
    the same call, leaving orphan Connect accounts.
    """
    stripe.api_key = settings.STRIPE_SECRET_KEY
    transfers = stripe.Transfer.list(transfer_group=transfer_group, limit=1)
    reversal_id: str | None = None
    if transfers.data:
        transfer = transfers.data[0]
        reversal = stripe.Transfer.create_reversal(
            transfer.id,
            amount=transfer.amount,
            idempotency_key=f"reversal:{transfer.id}",
        )
        reversal_id = reversal.id

    refund = stripe.Refund.create(
        charge=charge_id,
        amount=full_amount_cents,
        idempotency_key=f"refund:{charge_id}",
    )
    return RefundResult(refund_id=refund.id, reversal_id=reversal_id)
