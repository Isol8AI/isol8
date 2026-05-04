"""Service for Stripe billing operations — flat-fee model."""

import hashlib
import logging
import os
import time

import stripe

from core.config import settings
from core.observability.metrics import put_metric, timing
from core.repositories import billing_repo

logger = logging.getLogger(__name__)

stripe.api_key = settings.STRIPE_SECRET_KEY

FRONTEND_URL = os.getenv(
    "FRONTEND_URL", settings.cors_origins_list[0] if settings.cors_origins_list else "http://localhost:3000"
)


class BillingServiceError(Exception):
    pass


class BillingService:
    async def create_customer_for_owner(
        self, owner_id: str, owner_type: str = "personal", email: str | None = None
    ) -> dict:
        """Resolve a Stripe customer for ``owner_id``, keyed by ``email``.

        Email is the system-of-record idempotency key for Stripe-side identity:
        a single human (one verified email in Clerk) maps to a single Stripe
        Customer, regardless of how many billing entities they own (personal
        account, multiple orgs as admin, etc.). DDB ``billing-accounts`` rows
        are still per-owner_id, so multiple rows can share one
        ``stripe_customer_id``.

        Resolution order:
          1. Existing DDB row for this owner_id → return it (no Stripe call).
          2. ``stripe.Customer.list(email=...)`` → reuse the most recent match.
             ``list`` is exact-match and immediately consistent (unlike
             ``search``, which has indexing lag).
          3. No match → ``stripe.Customer.create``.

        Webhook handlers must resolve owner via subscription metadata
        (``owner_id``) since the GSI on ``stripe_customer_id`` is no longer
        unique. See ``handle_stripe_webhook`` in ``routers/billing.py``.
        """
        existing = await billing_repo.get_by_owner_id(owner_id)
        if existing:
            return existing

        # Normalize so a single human typing/signing in with mixed case
        # ("User@Example.com" vs "user@example.com") still maps to one
        # Stripe customer. Stripe's Customer.list email filter is exact
        # match, so without normalization we'd silently create duplicates.
        normalized_email = email.strip().lower() if email else None

        customer_id: str | None = None
        created_locally = False
        if normalized_email:
            with timing("stripe.api.latency", {"op": "customers.list"}):
                matches = stripe.Customer.list(email=normalized_email, limit=1)
            if matches and matches.data:
                customer_id = matches.data[0].id
                put_metric("stripe.customer.email_dedup", dimensions={"result": "reuse"})
                logger.info(
                    "Reusing Stripe customer %s for owner_id=%s (email=%s)",
                    customer_id,
                    owner_id,
                    normalized_email,
                )

        if customer_id is None:
            with timing("stripe.api.latency", {"op": "customers.create"}):
                customer = stripe.Customer.create(
                    email=normalized_email,
                    metadata={"owner_id": owner_id, "owner_type": owner_type},
                )
            customer_id = customer.id
            created_locally = True
            put_metric("stripe.customer.email_dedup", dimensions={"result": "create"})

        try:
            return await billing_repo.create_if_not_exists(
                owner_id=owner_id,
                stripe_customer_id=customer_id,
                owner_type=owner_type,
            )
        except billing_repo.AlreadyExistsError:
            # Lost the DDB race for this owner_id. If we took the create
            # path, two concurrent callers may have both missed the
            # email-list lookup and each minted a fresh Stripe customer —
            # the loser's customer is now orphaned (no DDB row points at
            # it). Delete it so the email→customer invariant holds.
            winner = await billing_repo.get_by_owner_id(owner_id)
            if (
                created_locally
                and winner
                and winner.get("stripe_customer_id")
                and winner["stripe_customer_id"] != customer_id
            ):
                logger.info(
                    "Lost DDB race for owner_id=%s; deleting orphan Stripe customer %s (winner=%s)",
                    owner_id,
                    customer_id,
                    winner["stripe_customer_id"],
                )
                try:
                    with timing("stripe.api.latency", {"op": "customers.delete"}):
                        stripe.Customer.delete(
                            customer_id,
                            idempotency_key=f"delete_customer:{customer_id}",
                        )
                    put_metric("stripe.customer.orphan_delete", dimensions={"result": "ok"})
                except Exception:
                    put_metric("stripe.customer.orphan_delete", dimensions={"result": "error"})
                    logger.warning("Failed to delete orphan Stripe customer %s", customer_id)
            return winner

    async def create_portal_session(self, billing_account: dict) -> str:
        owner_id = billing_account["owner_id"]
        # 5-minute time bucket — same retry-collapsing intent as checkout.
        bucket = int(time.time() // 300)
        with timing("stripe.api.latency", {"op": "billing_portal.session.create"}):
            session = stripe.billing_portal.Session.create(
                customer=billing_account["stripe_customer_id"],
                return_url=f"{FRONTEND_URL}/settings/billing",
                idempotency_key=f"portal:{owner_id}:{bucket}",
            )
        return session.url

    async def cancel_subscription(self, billing_account: dict) -> None:
        await billing_repo.set_subscription(
            owner_id=billing_account["owner_id"],
            subscription_id=None,
            status="canceled",
            trial_end=None,
        )


async def create_flat_fee_checkout(
    *,
    owner_id: str,
    provider_choice: str | None = None,
    byo_provider: str | None = None,
    clerk_user_id: str | None = None,
    trial_days: int | None = 14,
) -> stripe.checkout.Session:
    """Create a Stripe Checkout session on the single flat-fee price.

    Used by the flat-fee onboarding wizard (frontend cards 1, 2, 3 — all three
    pay the same monthly fee against ``STRIPE_FLAT_PRICE_ID``). When
    ``trial_days`` is set, the resulting subscription has a trial of that
    length and Stripe charges nothing until the trial converts.

    ``provider_choice``, ``clerk_user_id`` and ``owner_id`` are threaded into
    ``subscription_data.metadata`` so the ``customer.subscription.*`` webhook
    can resolve the owner unambiguously. ``owner_id`` matters because the
    Stripe customer is shared across personal/org billing rows for the same
    email — the GSI on ``stripe_customer_id`` is no longer 1:1.

    Conventions (mirrors Plan 1 Stripe Tax setup):
      - ``automatic_tax={"enabled": True}`` — Stripe computes sales tax/VAT.
      - ``customer_update={"address": "auto"}`` — required when automatic_tax
        is enabled so Checkout can persist the collected billing address back
        onto the existing Stripe customer.
      - ``allow_promotion_codes=True`` — surfaces the promo-code field so
        internal coupons (e.g. 100%-off launch codes) can be applied.
      - ``idempotency_key`` bucketed to a 5-minute window: collapses
        rapid duplicate clicks (and "open Stripe Checkout in two tabs"
        style retries) to a single Checkout Session, so a user can't
        accidentally complete two parallel subscriptions before the
        first ``customer.subscription.created`` webhook lands and the
        guard in ``create_trial_checkout`` kicks in. Stripe's
        idempotency does a body-shape compare, so a config change
        (e.g. ``allow_promotion_codes`` flipping on) naturally
        bypasses the cached response within the same bucket.
    """
    if not settings.STRIPE_FLAT_PRICE_ID:
        raise BillingServiceError("STRIPE_FLAT_PRICE_ID not configured")

    account = await billing_repo.get_by_owner_id(owner_id)
    if not account or not account.get("stripe_customer_id"):
        raise BillingServiceError(f"No Stripe customer for owner_id={owner_id}")

    subscription_data: dict = {}
    if trial_days is not None and trial_days > 0:
        subscription_data["trial_period_days"] = trial_days
    metadata: dict = {"owner_id": owner_id}
    if provider_choice:
        metadata["provider_choice"] = provider_choice
    if byo_provider:
        metadata["byo_provider"] = byo_provider
    if clerk_user_id:
        metadata["clerk_user_id"] = clerk_user_id
    subscription_data["metadata"] = metadata

    kwargs: dict = dict(
        customer=account["stripe_customer_id"],
        mode="subscription",
        line_items=[{"price": settings.STRIPE_FLAT_PRICE_ID, "quantity": 1}],
        success_url=(
            f"{FRONTEND_URL}/chat?checkout=success" + (f"&provider={provider_choice}" if provider_choice else "")
        ),
        cancel_url=f"{FRONTEND_URL}/?checkout=cancel",
        allow_promotion_codes=True,
        automatic_tax={"enabled": True},
        customer_update={"address": "auto"},
        subscription_data=subscription_data,
        idempotency_key=f"flat_checkout:{owner_id}:{provider_choice or '_'}:{int(time.time() // 300)}",
    )

    with timing("stripe.api.latency", {"op": "checkout.session.create"}):
        session = stripe.checkout.Session.create(**kwargs)
    return session


async def create_credit_top_up_checkout(
    *,
    owner_id: str,
    user_id: str,
    amount_cents: int,
) -> stripe.checkout.Session:
    """Create a Stripe Checkout session for a one-shot Claude-credit top-up.

    Replaces the legacy inline-Elements flow (PaymentIntent + Stripe.js)
    with a server-rendered Checkout page. Wins:

      - ``allow_promotion_codes=True`` lets internal users apply your
        existing 100%-off coupon directly on the Checkout page — Stripe
        handles validation and discount math, and the resulting
        ``$0`` charge incurs no Stripe fee.
      - No publishable key needed in the frontend bundle (the
        ``NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY`` env-var bug class goes
        away entirely).
      - Apple Pay / Google Pay / Link / saved cards / 3DS / SCA all
        come for free.

    Conventions match :func:`create_flat_fee_checkout`:
      - ``automatic_tax`` enabled + ``customer_update.address=auto``.
      - ``idempotency_key`` includes a per-request nonce because legitimate
        repeat top-ups for the same amount must produce distinct sessions
        — bucketing on owner_id+amount would silently collapse a second
        top-up onto the first.

    The credit grant happens asynchronously when Stripe fires
    ``checkout.session.completed`` with metadata
    ``{"purpose": "credit_top_up", "user_id": ...}``.
    """
    if amount_cents < 500:
        raise BillingServiceError("Minimum top-up is $5 (500 cents)")

    account = await billing_repo.get_by_owner_id(owner_id)
    if not account or not account.get("stripe_customer_id"):
        raise BillingServiceError(f"No Stripe customer for owner_id={owner_id}")

    # Per-request nonce — see docstring. Hashed to keep the key short.
    nonce = hashlib.sha1(os.urandom(16)).hexdigest()[:12]

    with timing("stripe.api.latency", {"op": "checkout.session.create"}):
        session = stripe.checkout.Session.create(
            customer=account["stripe_customer_id"],
            mode="payment",
            line_items=[
                {
                    "price_data": {
                        "currency": "usd",
                        "unit_amount": amount_cents,
                        "product_data": {
                            "name": "Claude credits",
                            "description": ("Prepaid Claude inference balance. Credits deducted at 1.4× Bedrock cost."),
                        },
                    },
                    "quantity": 1,
                }
            ],
            success_url=(f"{FRONTEND_URL}/chat?credits=success"),
            cancel_url=f"{FRONTEND_URL}/chat?credits=cancel",
            allow_promotion_codes=True,
            automatic_tax={"enabled": True},
            customer_update={"address": "auto"},
            payment_intent_data={
                "metadata": {
                    "purpose": "credit_top_up",
                    "user_id": user_id,
                },
            },
            metadata={
                "purpose": "credit_top_up",
                "user_id": user_id,
                "amount_cents": str(amount_cents),
            },
            idempotency_key=f"credit_checkout:{owner_id}:{nonce}",
        )
    return session


async def create_trial_subscription(*, owner_id: str, payment_method_id: str) -> stripe.Subscription:
    """Create a Stripe Subscription with a 14-day trial.

    Per spec §7.1 / §7.3: backend creates the Subscription IMMEDIATELY at
    signup against the saved payment method. Stripe handles conversion on
    day 15 (Smart Retries on failure). Backend just listens to the
    resulting webhooks (Plan 3 Task 2).

    The subscription is born in ``status: trialing`` with ``trial_end`` 14
    days out. Subscription id + initial status are persisted via
    :func:`billing_repo.set_subscription` so the rest of the system can
    read trial state without re-querying Stripe.

    Conventions:
      - ``automatic_tax={"enabled": True}`` — same Stripe Tax setup as
        :func:`create_flat_fee_checkout`.
      - ``payment_behavior="default_incomplete"`` — surfaces 3DS challenges
        to the frontend instead of auto-failing the create call.
      - ``payment_settings.save_default_payment_method=on_subscription``
        means a successful first charge persists the PM as the default
        for future invoices (no re-prompt at trial conversion).
      - ``idempotency_key=f"trial_signup:{owner_id}"`` — deterministic per
        user. A retry of the same trial-create call returns the same
        Stripe subscription, never duplicates.
    """
    if not settings.STRIPE_FLAT_PRICE_ID:
        raise BillingServiceError("STRIPE_FLAT_PRICE_ID not configured")

    account = await billing_repo.get_by_owner_id(owner_id)
    if not account or not account.get("stripe_customer_id"):
        raise BillingServiceError(f"No Stripe customer for owner_id={owner_id}")

    with timing("stripe.api.latency", {"op": "subscription.create"}):
        sub = stripe.Subscription.create(
            customer=account["stripe_customer_id"],
            items=[{"price": settings.STRIPE_FLAT_PRICE_ID}],
            trial_period_days=14,
            default_payment_method=payment_method_id,
            automatic_tax={"enabled": True},
            payment_behavior="default_incomplete",
            payment_settings={
                "save_default_payment_method": "on_subscription",
                "payment_method_types": ["card"],
            },
            idempotency_key=f"trial_signup:{owner_id}",
        )

    await billing_repo.set_subscription(
        owner_id=owner_id,
        subscription_id=sub.id,
        status=sub.status,
        trial_end=getattr(sub, "trial_end", None),
    )
    return sub


# ---------------------------------------------------------------------------
# Module-level admin wrappers
# ---------------------------------------------------------------------------
#
# Used by routers/admin.py — operate by Clerk user_id rather than billing_account
# dict so the admin router doesn't have to load the row first. Each function
# loads billing_repo + calls Stripe + updates DDB. Errors raise BillingServiceError.


async def cancel_subscription_for_owner(user_id: str) -> dict:
    """Admin: cancel a user's Stripe subscription. Idempotent on no-sub."""
    billing = await billing_repo.get_by_owner_id(user_id)
    if not billing:
        return {"status": "no_billing_account"}
    sub_id = billing.get("stripe_subscription_id")
    if not sub_id:
        return {"status": "no_subscription"}
    try:
        stripe.Subscription.delete(
            sub_id,
            idempotency_key=f"sub_cancel:{sub_id}",
        )
    except Exception as e:  # noqa: BLE001
        raise BillingServiceError(f"stripe_cancel_failed: {e}")
    await BillingService().cancel_subscription(billing)
    return {"status": "cancelled", "subscription_id": sub_id}


async def pause_subscription_for_owner(user_id: str) -> dict:
    """Admin: pause Stripe subscription billing (mark_uncollectible)."""
    billing = await billing_repo.get_by_owner_id(user_id)
    if not billing or not billing.get("stripe_subscription_id"):
        return {"status": "no_subscription"}
    sub_id = billing["stripe_subscription_id"]
    try:
        stripe.Subscription.modify(
            sub_id,
            pause_collection={"behavior": "mark_uncollectible"},
            idempotency_key=f"sub_modify:{sub_id}:pause",
        )
    except Exception as e:  # noqa: BLE001
        raise BillingServiceError(f"stripe_pause_failed: {e}")
    return {"status": "paused", "subscription_id": sub_id}


async def issue_credit_for_owner(user_id: str, *, amount_cents: int, reason: str) -> dict:
    """Admin: credit the user's Stripe customer balance by amount_cents.

    Stripe applies negative balance amounts as a credit toward future invoices.
    """
    billing = await billing_repo.get_by_owner_id(user_id)
    if not billing or not billing.get("stripe_customer_id"):
        return {"status": "no_customer"}
    customer_id = billing["stripe_customer_id"]
    # No admin_action_id is threaded through here yet, so derive a stable
    # hash from (amount, reason). Two genuinely-different credits with the
    # same reason but different amounts get different keys; a retry of the
    # same logical credit collapses to one Stripe write.
    reason_hash = hashlib.sha256(f"{amount_cents}:{reason}".encode("utf-8")).hexdigest()[:16]
    try:
        txn = stripe.Customer.create_balance_transaction(
            customer_id,
            amount=-abs(amount_cents),
            currency="usd",
            description=reason,
            idempotency_key=f"balance_tx:{customer_id}:{reason_hash}",
        )
    except Exception as e:  # noqa: BLE001
        raise BillingServiceError(f"stripe_credit_failed: {e}")
    return {"status": "credited", "transaction_id": txn["id"], "amount_cents": amount_cents}


async def mark_invoice_resolved(user_id: str, invoice_id: str) -> dict:
    """Admin: mark a Stripe invoice as paid out-of-band (e.g. wire transfer)."""
    try:
        invoice = stripe.Invoice.pay(
            invoice_id,
            paid_out_of_band=True,
            idempotency_key=f"invoice_pay:{invoice_id}",
        )
    except Exception as e:  # noqa: BLE001
        raise BillingServiceError(f"stripe_invoice_pay_failed: {e}")
    return {"status": "resolved", "invoice_id": invoice_id, "stripe_status": invoice.get("status")}
