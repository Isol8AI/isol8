"""Billing API endpoints — hybrid tier model with usage-based billing."""

import asyncio
import logging
import time

import httpx
import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from core.auth import AuthContext, get_current_user, resolve_owner_id, get_owner_type, require_org_admin
from core.config import settings, TIER_CONFIG
from core.observability.metrics import put_metric, timing
from core.repositories import billing_repo, usage_repo
from core.services import credit_ledger
from core.services.billing_service import (
    AlreadySubscribedError,
    BillingService,
    BillingServiceError,
)
from core.services.usage_service import check_budget, get_usage_summary
from core.services.bedrock_pricing import get_all_prices
from core.services.update_service import queue_tier_change
from core.services.config_patcher import ConfigPatchError
from schemas.billing import (
    BillingAccountResponse,
    CheckoutRequest,
    CheckoutResponse,
    PortalResponse,
    OverageToggleRequest,
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
    # Read-only endpoint. We intentionally do NOT auto-create a billing row
    # when the caller has no account — check_budget handles `None` by falling
    # through to free-tier defaults (see core/services/usage_service.py:128),
    # and the response shape is identical to a free-tier real account.
    # Billing rows are only written by POST /billing/checkout (explicit
    # subscribe intent, admin-gated for orgs).
    owner_id = resolve_owner_id(auth)
    account = await _get_billing_account(auth)

    budget = await check_budget(owner_id)

    # Lifetime spend
    lifetime_usage = await usage_repo.get_period_usage(owner_id, "lifetime")
    lifetime_spend = (lifetime_usage["total_spend_microdollars"] if lifetime_usage else 0) / 1_000_000

    budget_percent = (budget["current_spend"] / budget["included_budget"] * 100) if budget["included_budget"] > 0 else 0

    # overage_limit only exists on real paid-tier rows; synthetic free-tier
    # response (account is None) always reports None.
    overage_limit = float(account["overage_limit"]) / 1_000_000 if account and account.get("overage_limit") else None

    return BillingAccountResponse(
        tier=budget["tier"],
        is_subscribed=budget["is_subscribed"],
        current_spend=budget["current_spend"],
        included_budget=budget["included_budget"],
        budget_percent=round(budget_percent, 1),
        lifetime_spend=lifetime_spend,
        overage_enabled=budget["overage_enabled"],
        overage_limit=overage_limit,
        within_included=budget["within_included"],
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
    description="Returns per-token model pricing with markup.",
    operation_id="get_pricing",
)
async def get_pricing(
    auth: AuthContext = Depends(get_current_user),
):
    owner_id = resolve_owner_id(auth)
    account = await billing_repo.get_by_owner_id(owner_id)
    tier = account.get("plan_tier", "free") if account else "free"
    tier_config = TIER_CONFIG.get(tier, TIER_CONFIG["free"])

    all_prices = get_all_prices()
    markup = settings.BILLING_MARKUP

    models = {}
    for model_id, price in all_prices.items():
        models[model_id] = ModelPriceResponse(
            input=price["input"] * markup,
            output=price["output"] * markup,
            cache_read=price["cache_read"] * markup,
            cache_write=price["cache_write"] * markup,
        )

    # Strip the amazon-bedrock/ prefix from tier model IDs for response
    primary = tier_config["primary_model"].replace("amazon-bedrock/", "")
    subagent = tier_config["subagent_model"].replace("amazon-bedrock/", "")

    return PricingResponse(
        models=models,
        markup=markup,
        tier_model=primary,
        subagent_model=subagent,
    )


@router.post(
    "/checkout",
    response_model=CheckoutResponse,
    summary="Create checkout session",
    description="Creates a Stripe Checkout session to subscribe to a plan.",
    operation_id="create_checkout",
)
async def create_checkout(
    request: CheckoutRequest,
    auth: AuthContext = Depends(get_current_user),
):
    if auth.is_org_context:
        require_org_admin(auth)

    billing_service = BillingService()
    account = await _get_billing_account(auth)
    if not account:
        owner_id = resolve_owner_id(auth)
        owner_type = get_owner_type(auth)
        # Pass the caller's email so the new Stripe customer is born
        # identifiable. For org context this is the admin who clicked
        # Subscribe (the org's first paying admin); for personal context
        # it's the user themselves. Requires the Clerk session token
        # template to include `"email": "{{user.primary_email_address}}"`.
        account = await billing_service.create_customer_for_owner(
            owner_id=owner_id,
            owner_type=owner_type,
            email=auth.email,
        )

    try:
        url = await billing_service.create_checkout_session(account, request.tier.value)
    except AlreadySubscribedError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return CheckoutResponse(checkout_url=url)


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


@router.put(
    "/overage",
    summary="Toggle overage",
    description="Enable or disable overage billing for the account.",
    operation_id="toggle_overage",
)
async def toggle_overage(
    request: OverageToggleRequest,
    auth: AuthContext = Depends(get_current_user),
):
    if auth.is_org_context:
        require_org_admin(auth)

    owner_id = resolve_owner_id(auth)
    account = await billing_repo.get_by_owner_id(owner_id)
    if not account:
        raise HTTPException(status_code=404, detail="Billing account not found")

    # Attach or detach the metered line item on the live Stripe subscription
    # FIRST. We only flip the DynamoDB flag if the Stripe write succeeds —
    # otherwise the two diverge and `record_usage` could try to report meter
    # events against a subscription that doesn't have the metered item
    # (Stripe would silently drop them and the customer would never be billed
    # for usage they actually consumed).
    billing_service = BillingService()
    try:
        await billing_service.set_metered_overage_item(account, request.enabled)
    except BillingServiceError as e:
        raise HTTPException(status_code=400, detail=str(e))

    limit_microdollars = int(request.limit_dollars * 1_000_000) if request.limit_dollars is not None else None
    await billing_repo.set_overage_enabled(owner_id, request.enabled, overage_limit=limit_microdollars)
    return {"status": "ok"}


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
            idempotency_key=f"top_up:{ctx.user_id}:{body.amount_cents}:{int(time.time() // 60)}",
        )
    return {"client_secret": pi.client_secret, "payment_intent_id": pi.id}


@router.put(
    "/credits/auto_reload",
    status_code=204,
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
    return Response(status_code=204)


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

    if event_type == "customer.subscription.created":
        put_metric("stripe.subscription", dimensions={"event": "created"})
        customer_id = event_data["customer"]
        subscription_id = event_data["id"]
        tier = event_data.get("metadata", {}).get("plan_tier", "starter")

        account = await billing_repo.get_by_stripe_customer_id(customer_id)
        if account:
            old_tier = account.get("plan_tier", "free")
            await billing_service.update_subscription(account, subscription_id, tier)
            logger.info("Subscription created for owner %s (tier=%s)", account["owner_id"], tier)
            try:
                await queue_tier_change(account["owner_id"], old_tier=old_tier, new_tier=tier)
            except ConfigPatchError:
                logger.warning(
                    "Could not patch config for owner %s (container may not be provisioned yet)", account["owner_id"]
                )
            except Exception:
                logger.exception("Failed to queue tier change for owner %s", account["owner_id"])

    elif event_type == "customer.subscription.updated":
        put_metric("stripe.subscription", dimensions={"event": "updated"})
        customer_id = event_data["customer"]
        tier = event_data.get("metadata", {}).get("plan_tier", "starter")

        account = await billing_repo.get_by_stripe_customer_id(customer_id)
        if account:
            old_tier = account.get("plan_tier", "free")
            await billing_service.update_subscription(account, event_data["id"], tier)
            try:
                await queue_tier_change(account["owner_id"], old_tier=old_tier, new_tier=tier)
            except ConfigPatchError:
                logger.warning(
                    "Could not patch config for owner %s (container may not be provisioned yet)", account["owner_id"]
                )
            except Exception:
                logger.exception("Failed to queue tier change for owner %s", account["owner_id"])

    elif event_type == "customer.subscription.deleted":
        put_metric("stripe.subscription", dimensions={"event": "deleted"})
        customer_id = event_data["customer"]

        account = await billing_repo.get_by_stripe_customer_id(customer_id)
        if account:
            old_tier = account.get("plan_tier", "free")
            await billing_service.cancel_subscription(account)
            logger.info("Subscription cancelled for owner %s", account["owner_id"])
            try:
                await queue_tier_change(account["owner_id"], old_tier=old_tier, new_tier="free")
            except ConfigPatchError:
                logger.warning(
                    "Could not patch config for owner %s (container may not be provisioned yet)", account["owner_id"]
                )
            except Exception:
                logger.exception("Failed to queue tier change for owner %s", account["owner_id"])

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
