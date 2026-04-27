"""Billing API endpoints — flat-fee model with credit ledger."""

import asyncio
import logging
import uuid

import httpx
import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from core.auth import AuthContext, get_current_user, get_owner_type, resolve_owner_id, require_org_admin
from core.config import settings
from core.observability.metrics import put_metric, timing
from core.repositories import billing_repo, usage_repo
from core.services import credit_ledger
from core.services.billing_service import BillingService
from core.services.usage_service import get_usage_summary
from core.services.bedrock_pricing import get_all_prices
from schemas.billing import (
    BillingAccountResponse,
    PortalResponse,
    UsageSummary,
    MemberUsage,
    MyUsageResponse,
    PricingResponse,
    ModelPriceResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


async def _resolve_clerk_user(user_id: str) -> dict:
    """Resolve a Clerk user ID to display name and email."""
    if not settings.CLERK_SECRET_KEY:
        return {}
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://api.clerk.com/v1/users/{user_id}",
                headers={"Authorization": f"Bearer {settings.CLERK_SECRET_KEY}"},
                timeout=5.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "display_name": f"{data.get('first_name', '')} {data.get('last_name', '')}".strip() or None,
                    "email": (data.get("email_addresses") or [{}])[0].get("email_address"),
                }
    except Exception:
        pass
    return {}


async def _get_billing_account(auth: AuthContext) -> dict | None:
    """Resolve billing account from auth context."""
    return await billing_repo.get_by_owner_id(resolve_owner_id(auth))


@router.get(
    "/account",
    response_model=BillingAccountResponse,
    summary="Get billing account",
    description="Returns billing account details with real spend data.",
    operation_id="get_billing_account",
)
async def get_billing_account(
    auth: AuthContext = Depends(get_current_user),
):
    # Read-only endpoint. We do not auto-create a billing row when the caller
    # has no account — billing rows are written by the trial-subscription
    # signup flow (Plan 3 §7.1). Callers without an account are pre-signup
    # users; the response just reflects "no subscription" defaults.
    owner_id = resolve_owner_id(auth)
    account = await _get_billing_account(auth)

    # Current-period spend for analytics. Counter-only — the credit ledger
    # is the authoritative billing surface for card-3 users.
    summary = await get_usage_summary(owner_id)
    current_spend = summary["total_spend"]
    lifetime_spend = summary["lifetime_spend"]

    # Stripe-native subscription state. Both fields come from billing_repo
    # .set_subscription (set on subscription create + refreshed by the
    # customer.subscription.updated webhook). Account is None for pre-signup
    # responses → both fields stay None.
    subscription_status = account.get("subscription_status") if account else None
    trial_end = account.get("trial_end") if account else None

    # is_subscribed is keyed off subscription_status when present, but falls
    # back to the legacy stripe_subscription_id marker for accounts that
    # predate the cutover or haven't yet received a customer.subscription
    # .updated webhook. Without the fallback, paid users get pushed back into
    # the payment phase. Codex P1 on PR #393.
    is_subscribed = subscription_status in ("active", "trialing") or (
        account is not None and bool(account.get("stripe_subscription_id"))
    )

    return BillingAccountResponse(
        is_subscribed=is_subscribed,
        current_spend=current_spend,
        lifetime_spend=lifetime_spend,
        subscription_status=subscription_status,
        trial_end=int(trial_end) if trial_end is not None else None,
    )


@router.get(
    "/usage",
    response_model=UsageSummary,
    summary="Get usage summary",
    description="Returns current period usage breakdown. Org admins see per-member usage.",
    operation_id="get_usage",
)
async def get_usage(
    auth: AuthContext = Depends(get_current_user),
):
    owner_id = resolve_owner_id(auth)
    summary = await get_usage_summary(owner_id)

    by_member: list[MemberUsage] = []

    # Org admins can see per-member breakdown
    if auth.is_org_context:
        require_org_admin(auth)
        members_raw = await usage_repo.get_member_usage(owner_id, summary["period"])

        # Resolve Clerk names in parallel
        async def _enrich(m: dict) -> MemberUsage:
            clerk_info = await _resolve_clerk_user(m["user_id"])
            return MemberUsage(
                user_id=m["user_id"],
                display_name=clerk_info.get("display_name"),
                email=clerk_info.get("email"),
                total_spend=m["total_spend_microdollars"] / 1_000_000,
                total_input_tokens=m["total_input_tokens"],
                total_output_tokens=m["total_output_tokens"],
                request_count=m["request_count"],
            )

        by_member = await asyncio.gather(*[_enrich(m) for m in members_raw])

    return UsageSummary(
        period=summary["period"],
        total_spend=summary["total_spend"],
        total_input_tokens=summary["total_input_tokens"],
        total_output_tokens=summary["total_output_tokens"],
        total_cache_read_tokens=summary["total_cache_read_tokens"],
        total_cache_write_tokens=summary["total_cache_write_tokens"],
        request_count=summary["request_count"],
        lifetime_spend=summary["lifetime_spend"],
        by_member=list(by_member),
    )


@router.get(
    "/my-usage",
    response_model=MyUsageResponse,
    summary="Get current user's own usage",
    description="Returns the authenticated user's personal usage for the current billing period. No admin gating — any authenticated user can see their own usage.",
    operation_id="get_my_usage",
)
async def get_my_usage(
    auth: AuthContext = Depends(get_current_user),
):
    from datetime import datetime, timezone

    owner_id = resolve_owner_id(auth)
    user_id = auth.user_id

    now = datetime.now(timezone.utc)
    period = f"{now.year}-{now.month:02d}"

    member_key = f"member:{user_id}:{period}"
    member_usage = await usage_repo.get_period_usage(owner_id, member_key)

    return MyUsageResponse(
        period=period,
        total_spend=(member_usage["total_spend_microdollars"] if member_usage else 0) / 1_000_000,
        total_input_tokens=member_usage["total_input_tokens"] if member_usage else 0,
        total_output_tokens=member_usage["total_output_tokens"] if member_usage else 0,
        request_count=member_usage["request_count"] if member_usage else 0,
    )


@router.get(
    "/pricing",
    response_model=PricingResponse,
    summary="Get model pricing",
    description=(
        "Returns per-token Bedrock Claude pricing for the credit-ledger UI. "
        "Card-3 (bedrock_claude) users pay raw Bedrock prices times the credit-ledger "
        "markup (applied on deduct, not surfaced here)."
    ),
    operation_id="get_pricing",
)
async def get_pricing(
    auth: AuthContext = Depends(get_current_user),
):
    all_prices = get_all_prices()
    models = {
        model_id: ModelPriceResponse(
            input=price["input"],
            output=price["output"],
            cache_read=price["cache_read"],
            cache_write=price["cache_write"],
        )
        for model_id, price in all_prices.items()
    }
    return PricingResponse(models=models)


@router.post(
    "/portal",
    response_model=PortalResponse,
    summary="Create customer portal session",
    description="Creates a Stripe Customer Portal session for payment management.",
    operation_id="create_portal",
)
async def create_portal(
    auth: AuthContext = Depends(get_current_user),
):
    if auth.is_org_context:
        require_org_admin(auth)

    account = await _get_billing_account(auth)
    if not account:
        raise HTTPException(status_code=404, detail="Billing account not found")

    billing_service = BillingService()
    url = await billing_service.create_portal_session(account)
    return PortalResponse(portal_url=url)


# ---------------------------------------------------------------------------
# Trial signup — single endpoint that backs the ProviderPicker cards.
# ---------------------------------------------------------------------------


class TrialCheckoutRequest(BaseModel):
    provider_choice: str = Field(..., description="chatgpt_oauth | byo_key | bedrock_claude")


@router.post(
    "/trial-checkout",
    summary="Start a 14-day trial via Stripe Checkout",
    description=(
        "Creates a Stripe Checkout session in subscription mode with a 14-day trial. "
        "Charges $0 today; user enters card details, the Subscription is born trialing, "
        "and Stripe converts it on day 15. The chosen provider_choice is threaded into "
        "subscription metadata so the webhook handler can persist it on the user row. "
        "Returns the Checkout URL — frontend redirects the browser to it."
    ),
    operation_id="create_trial_checkout",
)
async def create_trial_checkout(
    body: TrialCheckoutRequest,
    auth: AuthContext = Depends(get_current_user),
):
    from core.services.billing_service import (
        BillingService,
        BillingServiceError,
        create_flat_fee_checkout,
    )

    if body.provider_choice not in ("chatgpt_oauth", "byo_key", "bedrock_claude"):
        raise HTTPException(status_code=400, detail="unknown provider_choice")

    # Org-context callers must be admins — without this gate any org member
    # could create a Stripe Checkout against the org's billing account and
    # spawn a parallel subscription. Codex P1 on PR #393.
    if auth.is_org_context:
        require_org_admin(auth)

    owner_id = resolve_owner_id(auth)
    account = await _get_billing_account(auth)
    if not account:
        owner_type = get_owner_type(auth)
        billing_service = BillingService()
        account = await billing_service.create_customer_for_owner(
            owner_id=owner_id,
            owner_type=owner_type,
            email=auth.email,
        )

    # Refuse a second trial-checkout when an active/trialing subscription
    # already exists. Stripe Checkout in mode="subscription" creates a NEW
    # subscription on every successful return, so a retry past the 5-minute
    # idempotency-bucket window would charge the customer twice. Codex P1
    # on PR #393.
    existing_status = account.get("subscription_status")
    if existing_status in ("active", "trialing", "past_due") or account.get("stripe_subscription_id"):
        # Allow retries when the existing row is canceled / incomplete /
        # incomplete_expired — those don't bill, and the user genuinely
        # needs to be able to start a fresh trial. Match the criteria used
        # by the legacy create_checkout_session guard (see PR #389).
        if existing_status in ("active", "trialing", "past_due"):
            raise HTTPException(
                status_code=409,
                detail=f"already_subscribed:{existing_status}",
            )

    try:
        session = await create_flat_fee_checkout(
            owner_id=owner_id,
            provider_choice=body.provider_choice,
            # auth.user_id is the Clerk user actually clicking the button —
            # in org context this is the admin, NOT the org id. Threaded
            # through subscription_data.metadata so the webhook can persist
            # provider_choice on the right per-Clerk-user row. Codex P1.
            clerk_user_id=auth.user_id,
            trial_days=14,
        )
    except BillingServiceError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"checkout_url": session.url}


# ---------------------------------------------------------------------------
# Credit ledger endpoints (Plan 2 §6.2 / §6.4)
# ---------------------------------------------------------------------------


class TopUpRequest(BaseModel):
    amount_cents: int = Field(..., ge=500, description="Minimum $5 (500 cents)")


class AutoReloadRequest(BaseModel):
    enabled: bool
    threshold_cents: int | None = Field(default=None, ge=500)
    amount_cents: int | None = Field(default=None, ge=500)


@router.get(
    "/credits/balance",
    summary="Get the user's prepaid credit balance",
    description=("Returns the user's current prepaid Claude credit balance in microcents and dollars (formatted)."),
)
async def get_credits_balance(ctx: AuthContext = Depends(get_current_user)):
    balance_uc = await credit_ledger.get_balance(ctx.user_id)
    dollars = f"{balance_uc / 1_000_000:.2f}"
    return {"balance_microcents": balance_uc, "balance_dollars": dollars}


@router.post(
    "/credits/top_up",
    summary="Buy credits via Stripe PaymentIntent",
    description=(
        "Creates a Stripe PaymentIntent for one-time credit purchase. "
        "Returns client_secret for Stripe.js confirmation. Minimum $5."
    ),
)
async def top_up_credits(
    body: TopUpRequest,
    ctx: AuthContext = Depends(get_current_user),
):
    if body.amount_cents < 500:
        raise HTTPException(status_code=400, detail="Minimum top-up is $5 (500 cents)")
    account = await billing_repo.get_by_owner_id(ctx.user_id)
    if not account or not account.get("stripe_customer_id"):
        raise HTTPException(status_code=400, detail="No Stripe customer on file")

    # Idempotency key is a per-request UUID so two legitimate top-ups of the
    # same amount (even within the same minute) create distinct PaymentIntents.
    # The double-submit guard is a frontend concern (the Pay button disables
    # itself + the page reloads on success). Codex P2 on PR #393 — using a
    # minute bucket meant a second top-up could collapse onto the first
    # PaymentIntent and silently skip the credit grant.
    with timing("stripe.api.latency", {"op": "payment_intent.create"}):
        pi = stripe.PaymentIntent.create(
            amount=body.amount_cents,
            currency="usd",
            customer=account["stripe_customer_id"],
            automatic_payment_methods={"enabled": True},
            metadata={
                "purpose": "credit_top_up",
                "user_id": ctx.user_id,
            },
            idempotency_key=f"top_up:{ctx.user_id}:{uuid.uuid4().hex}",
        )
    return {"client_secret": pi.client_secret, "payment_intent_id": pi.id}


@router.put(
    "/credits/auto_reload",
    summary="Configure auto-reload",
    description=("Configure auto-reload: when balance drops below threshold_cents, charge amount_cents off-session."),
)
async def set_auto_reload(
    body: AutoReloadRequest,
    ctx: AuthContext = Depends(get_current_user),
):
    if body.enabled and (body.threshold_cents is None or body.amount_cents is None):
        raise HTTPException(
            status_code=400,
            detail="threshold_cents and amount_cents required when enabling",
        )
    await credit_ledger.set_auto_reload(
        ctx.user_id,
        enabled=body.enabled,
        threshold_cents=body.threshold_cents,
        amount_cents=body.amount_cents,
    )
    # Return JSON (not 204) — the frontend `useApi` helper unconditionally
    # parses successful responses with .json(), so an empty body is read as
    # a parse failure and surfaces as an error in CreditsPanel. Codex P2 on
    # PR #393.
    return {"status": "ok"}


@router.post(
    "/webhooks/stripe",
    summary="Handle Stripe webhooks",
    description="Processes Stripe webhook events for subscription lifecycle.",
    operation_id="handle_stripe_webhook",
    include_in_schema=False,
)
async def handle_stripe_webhook(
    request: Request,
):
    """Handle Stripe webhook events. No Clerk auth — uses Stripe signature."""
    body = await request.body()
    sig = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(body, sig, settings.STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        put_metric("stripe.webhook.sig_fail")
        logger.error("Stripe webhook signature verification failed: %s", e)
        raise HTTPException(status_code=400, detail="Invalid signature")

    # Dedup check — Stripe replays webhooks on any non-2xx and on its own
    # at-least-once delivery insurance. The local import keeps the helper's
    # boto3 client out of cold-start until first use.
    from core.services.webhook_dedup import (
        WebhookDedupResult,
        record_event_or_skip,
    )

    dedup = await record_event_or_skip(event["id"], source="stripe")
    if dedup is WebhookDedupResult.ALREADY_SEEN:
        put_metric(
            "stripe.webhook.dedup_skipped",
            dimensions={"event_type": event["type"]},
        )
        return Response(status_code=200)

    event_type = event["type"]
    put_metric("stripe.webhook.received", dimensions={"event_type": event_type})
    event_data = event["data"]["object"]

    billing_service = BillingService()

    if event_type == "customer.subscription.updated":
        # Single source of truth for subscription-state sync. Fires on trial
        # start, payment-method updates, status transitions (trialing →
        # active, active → past_due, etc.), and cancellation-at-period-end.
        # We just persist the Stripe-side state so the frontend can render
        # trial banners + access gates without a Stripe round-trip.
        put_metric(
            "stripe.subscription",
            dimensions={"event": "updated", "status": event_data.get("status", "unknown")},
        )
        customer_id = event_data["customer"]
        account = await billing_repo.get_by_stripe_customer_id(customer_id)
        if account:
            await billing_repo.set_subscription(
                owner_id=account["owner_id"],
                subscription_id=event_data["id"],
                status=event_data.get("status", "active"),
                trial_end=event_data.get("trial_end"),
            )
            # Trial-checkout threads provider_choice + clerk_user_id into
            # subscription metadata so we can persist provider_choice on
            # the right per-Clerk-user row. account["owner_id"] is the
            # org_id in org context, which is NOT a valid user_repo key —
            # chat gating reads provider_choice keyed by Clerk user_id.
            # Codex P1 on PR #393.
            metadata = event_data.get("metadata") or {}
            metadata_provider = metadata.get("provider_choice")
            metadata_clerk_user_id = metadata.get("clerk_user_id") or account["owner_id"]
            if metadata_provider in ("chatgpt_oauth", "byo_key", "bedrock_claude"):
                from core.repositories import user_repo

                try:
                    await user_repo.set_provider_choice(
                        metadata_clerk_user_id,
                        provider_choice=metadata_provider,
                    )
                except Exception:
                    logger.exception(
                        "Failed to persist provider_choice from sub metadata for clerk_user_id %s",
                        metadata_clerk_user_id,
                    )

    elif event_type == "customer.subscription.trial_will_end":
        # Plan 3 §7.2 + §8.2: Stripe fires this 3 days before trial_end. We
        # just emit a metric so we can see how often it fires; Stripe sends
        # its own default reminder email regardless. A branded reminder
        # email via SES is a follow-up.
        put_metric("trial.will_end_3day")
        customer_id = event_data["customer"]
        account = await billing_repo.get_by_stripe_customer_id(customer_id)
        if account:
            logger.info(
                "Trial will end in 3 days for owner %s (trial_end=%s)",
                account["owner_id"],
                event_data.get("trial_end"),
            )

    elif event_type == "customer.subscription.deleted":
        put_metric("stripe.subscription", dimensions={"event": "deleted"})
        customer_id = event_data["customer"]

        account = await billing_repo.get_by_stripe_customer_id(customer_id)
        if account:
            await billing_service.cancel_subscription(account)
            logger.info("Subscription cancelled for owner %s", account["owner_id"])

            # Tear down the user's container — they no longer have an active
            # subscription. Best-effort; log and continue on failure so we
            # don't 500 the webhook back to Stripe.
            try:
                from core.containers import get_ecs_manager

                await get_ecs_manager().delete_user_service(account["owner_id"])
            except Exception:
                logger.exception(
                    "Container teardown on subscription.deleted failed for owner %s",
                    account["owner_id"],
                )

    elif event_type == "invoice.payment_failed":
        put_metric("stripe.subscription", dimensions={"event": "payment_failed"})
        logger.warning("Payment failed for customer %s", event_data.get("customer"))

    elif event_type == "invoice.paid":
        logger.info("Payment succeeded for customer %s", event_data.get("customer"))

    elif event_type == "payment_intent.succeeded":
        pi = event["data"]["object"]
        if pi.get("metadata", {}).get("purpose") != "credit_top_up":
            # Some other payment intent (e.g. Stripe-internal). Ignore.
            return Response(status_code=200)

        user_id = pi["metadata"].get("user_id")
        if not user_id:
            logger.error("Credit top-up webhook missing user_id metadata: %s", pi["id"])
            return Response(status_code=200)

        # 1 cent = 10_000 microcents. PaymentIntent.amount is in cents.
        amount_microcents = int(pi["amount"]) * 10_000
        await credit_ledger.top_up(
            user_id,
            amount_microcents=amount_microcents,
            stripe_payment_intent_id=pi["id"],
        )
        put_metric(
            "credit.top_up",
            value=pi["amount"] / 100.0,
            unit="None",
            dimensions={"source": "stripe_payment_intent"},
        )

    return {"status": "ok"}
