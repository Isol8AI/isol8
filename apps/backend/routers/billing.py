"""Billing API endpoints — flat-fee model with credit ledger."""

import asyncio
import logging

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
from core.billing.bedrock_pricing import get_all_rates
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
    # Schema convention is USD per token; rate table is USD per million
    # tokens. Convert here so the API contract is unchanged.
    all_rates = get_all_rates()
    models = {
        model_id: ModelPriceResponse(
            input=rate["input"] / 1_000_000,
            output=rate["output"] / 1_000_000,
            cache_read=rate["cache_read"] / 1_000_000,
            cache_write=rate["cache_write"] / 1_000_000,
        )
        for model_id, rate in all_rates.items()
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

    # Org-context users cannot pick ChatGPT OAuth — see
    # memory/project_chatgpt_oauth_personal_only.md (decision 2026-04-30:
    # OpenAI Plus terms forbid reselling, so org admins can't route their
    # teammates' prompts through their personal ChatGPT subscription; orgs
    # must use Bedrock or BYOK). Frontend ProviderPicker hides the card too,
    # but a savvy user could call this endpoint directly without server-side
    # enforcement. Reject before any Stripe Checkout creation so a denied
    # caller never gets a session URL.
    if body.provider_choice == "chatgpt_oauth" and auth.is_org_context:
        raise HTTPException(
            status_code=403,
            detail=(
                "ChatGPT OAuth is not available for organization workspaces. "
                "Use Bring-Your-Own-Key or Powered by Claude instead."
            ),
        )

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

    # Refuse a second trial-checkout for any subscription that exists,
    # regardless of state. Stripe Checkout in mode="subscription"
    # creates a NEW subscription on every successful return, so a retry
    # past the 5-minute idempotency-bucket window would charge the
    # customer twice (Codex P1 on PR #393).
    #
    # Originally this only blocked {active, trialing, past_due}, but
    # that left a trial-gaming hole (audit C3): a user could complete a
    # 14-day trial, cancel before day 15 (no charge), and immediately
    # POST /trial-checkout again to mint a new 14-day trial — repeating
    # forever. ECS Fargate is recurring on us either way; the trial
    # itself never charges. We now also block {canceled, incomplete,
    # incomplete_expired, unpaid, paused}. A user who legitimately wants
    # to re-subscribe after cancel must go through customer support so
    # we can verify they're not gaming the trial.
    _BLOCKED_REPEAT_STATUSES = frozenset(
        {
            "active",
            "trialing",
            "past_due",
            "canceled",
            "incomplete",
            "incomplete_expired",
            "unpaid",
            "paused",
        }
    )
    existing_status = account.get("subscription_status")
    has_legacy_sub = bool(account.get("stripe_subscription_id"))
    if existing_status in _BLOCKED_REPEAT_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"already_subscribed:{existing_status}",
        )
    # Legacy rows: stripe_subscription_id is set but subscription_status
    # hasn't been backfilled. Verify the live Stripe state instead of
    # creating a parallel subscription. Codex P1 round-4 on PR #393.
    if has_legacy_sub:
        sub_id = account["stripe_subscription_id"]
        try:
            with timing("stripe.api.latency", {"op": "subscription.retrieve"}):
                live_sub = stripe.Subscription.retrieve(sub_id)
        except stripe.error.InvalidRequestError as e:
            # "resource_missing" → Stripe forgot the sub (lost cancel
            # webhook); the local row is stale. Allow the new checkout.
            if getattr(e, "code", None) != "resource_missing":
                raise
            logger.info(
                "Stored sub %s not found in Stripe for owner %s — allowing fresh trial",
                sub_id,
                owner_id,
            )
        else:
            # Same expanded blocklist as the local-row path — a stale
            # canceled/incomplete subscription in Stripe is still a
            # "this account already trialed" signal (audit C3).
            if live_sub.get("status") in _BLOCKED_REPEAT_STATUSES:
                raise HTTPException(
                    status_code=409,
                    detail=f"already_subscribed:{live_sub.get('status')}",
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


# Hard caps on credit-purchase amounts. These exist as a safety rail
# (audit C4 / M4) — without an upper bound, a malicious or compromised
# user could (a) request a $99k off-session auto-reload that locks in a
# disputable charge, or (b) trick a phished user into pre-paying an
# unreasonable amount via Elements. Stripe will likely reject extremes
# itself, but defense in depth says we cap server-side too.
#
# Values are deliberately conservative; raise via a code change + a
# pricing-tier conversation rather than user-facing input.
_TOP_UP_MAX_CENTS = 100_000  # $1,000.00 — single-shot prepay ceiling
_AUTO_RELOAD_MAX_CENTS = 20_000  # $200.00 — recurring off-session ceiling


class TopUpRequest(BaseModel):
    amount_cents: int = Field(
        ...,
        ge=500,
        le=_TOP_UP_MAX_CENTS,
        description="Min $5 (500 cents), max $1,000 (100000 cents).",
    )


class AutoReloadRequest(BaseModel):
    enabled: bool
    threshold_cents: int | None = Field(default=None, ge=500, le=_AUTO_RELOAD_MAX_CENTS)
    amount_cents: int | None = Field(default=None, ge=500, le=_AUTO_RELOAD_MAX_CENTS)


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
    summary="Start a Stripe Checkout session for a credit top-up",
    description=(
        "Creates a Stripe Checkout session in mode=payment for a one-shot "
        "credit purchase. Returns ``checkout_url`` — the frontend redirects "
        "the browser to it. Stripe handles card collection, 3DS, Apple Pay, "
        "saved cards, and promotion-code application. The credit grant "
        "happens asynchronously when Stripe fires checkout.session.completed."
    ),
    operation_id="credits_top_up_checkout",
)
async def top_up_credits(
    body: TopUpRequest,
    ctx: AuthContext = Depends(get_current_user),
):
    """Replaces the previous inline-Elements PaymentIntent flow.

    Why Checkout > Elements for our usage:
      - Native promotion-code support → internal 100%-off coupon works.
      - Auto-reload (off-session) is unaffected — that path stays
        on direct PaymentIntents because there's no UI step.
      - No client-side Stripe SDK / publishable key required.
    """
    from core.services.billing_service import (
        BillingServiceError,
        create_credit_top_up_checkout,
    )

    owner_id = resolve_owner_id(ctx)
    try:
        session = await create_credit_top_up_checkout(
            owner_id=owner_id,
            user_id=ctx.user_id,
            amount_cents=body.amount_cents,
        )
    except BillingServiceError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"checkout_url": session.url}


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

    if event_type in ("customer.subscription.created", "customer.subscription.updated"):
        # Single source of truth for subscription-state sync. Fires on trial
        # start (.created), trial→active transitions, payment-method updates,
        # past_due transitions, and cancellation-at-period-end (all .updated).
        # We just persist the Stripe-side state so the frontend can render
        # trial banners + access gates without a Stripe round-trip.
        #
        # CRITICAL: Stripe Checkout for a brand-new trial emits
        # customer.subscription.CREATED first; .updated only fires on later
        # state transitions. Without the .created branch, the user's first
        # trial never persists subscription_status or provider_choice — they
        # get stuck on the ProviderPicker after returning from Checkout
        # because is_subscribed stays False.
        put_metric(
            "stripe.subscription",
            dimensions={
                "event": event_type.split(".")[-1],
                "status": event_data.get("status", "unknown"),
            },
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

            # Disable Paperclip for this owner with a 30-day grace window —
            # T13's cleanup cron purges the Paperclip-side artifacts after
            # the grace elapses. Only THIS user is disabled; if they own a
            # multi-member org the other members keep access until their
            # own subscriptions cancel (or the org is deleted in Clerk).
            from routers.webhooks import (
                _close_paperclip_http,
                _get_paperclip_provisioning,
            )

            provisioning = None
            try:
                provisioning = await _get_paperclip_provisioning()
                await provisioning.disable(user_id=account["owner_id"])
                put_metric(
                    "paperclip.webhook.disable",
                    dimensions={"trigger": "subscription_deleted"},
                )
            except Exception:
                logger.exception(
                    "Paperclip disable on subscription.deleted failed for owner %s",
                    account["owner_id"],
                )
            finally:
                if provisioning is not None:
                    await _close_paperclip_http(provisioning)

    elif event_type == "invoice.payment_failed":
        put_metric("stripe.subscription", dimensions={"event": "payment_failed"})
        logger.warning("Payment failed for customer %s", event_data.get("customer"))

    elif event_type == "invoice.paid":
        logger.info("Payment succeeded for customer %s", event_data.get("customer"))

    elif event_type in (
        "checkout.session.completed",
        "checkout.session.async_payment_succeeded",
    ):
        session = event["data"]["object"]
        # We piggyback on the same webhook for two distinct flows; only
        # credit-top-up sessions need ledger work here. Trial-checkout
        # sessions get their state from customer.subscription.created
        # / .updated above.
        if session.get("metadata", {}).get("purpose") != "credit_top_up":
            return Response(status_code=200)

        # Only grant credits when Stripe has actually collected payment.
        #   - "paid"               : card payment cleared synchronously.
        #   - "no_payment_required": 100%-off coupon → $0 charge → still
        #                            a valid credit grant (we absorb the
        #                            cost via the coupon).
        #   - "unpaid"             : delayed-payment method (ACH /
        #                            bank transfer / Klarna) hasn't
        #                            settled yet. Stripe fires
        #                            checkout.session.completed
        #                            immediately for these, then later
        #                            fires async_payment_succeeded
        #                            (or async_payment_failed). We
        #                            wait for the async event before
        #                            crediting so a failed ACH doesn't
        #                            leave the user with free credits.
        # Codex P1 on PR #488.
        payment_status = session.get("payment_status")
        if payment_status not in ("paid", "no_payment_required"):
            put_metric(
                "credit.top_up.deferred",
                dimensions={"payment_status": payment_status or "unknown"},
            )
            logger.info(
                "Credit top-up deferred for session %s — payment_status=%s",
                session.get("id"),
                payment_status,
            )
            return Response(status_code=200)

        user_id = session["metadata"].get("user_id")
        amount_cents_str = session["metadata"].get("amount_cents")
        if not user_id or not amount_cents_str:
            logger.error("Credit top-up checkout.session missing metadata: %s", session.get("id"))
            return Response(status_code=200)

        # Credit the *requested* amount, not what Stripe actually charged.
        # If the user redeemed a 100%-off internal coupon, Stripe charged
        # nothing but we still grant the full credit balance — the coupon
        # is effectively us absorbing the cost so internal teams can fund
        # their own usage without per-transaction Stripe fees. For partial
        # discounts the same rule applies: the user paid less, but the
        # ledger reflects the credits-promised side of the transaction.
        amount_cents = int(amount_cents_str)
        amount_microcents = amount_cents * 10_000
        await credit_ledger.top_up(
            user_id,
            amount_microcents=amount_microcents,
            # Use session id as the idempotency key on the ledger side —
            # one Checkout completion = one credit grant, even if Stripe
            # retries the webhook delivery (or fires both completed +
            # async_payment_succeeded back-to-back).
            stripe_payment_intent_id=session.get("id"),
        )
        amount_total = session.get("amount_total")
        put_metric(
            "credit.top_up",
            value=(amount_total or 0) / 100.0,
            unit="None",
            dimensions={
                "source": "stripe_checkout",
                "discounted": "true" if amount_total != amount_cents else "false",
                "event": event_type.split(".")[-1],
            },
        )

    elif event_type == "checkout.session.async_payment_failed":
        # Delayed-payment method (ACH / bank transfer) was rejected after
        # checkout.session.completed had already fired with payment_status
        # = "unpaid". Because we *gate* the credit grant on payment_status,
        # nothing was ever credited — but emit a metric so we can see the
        # fail rate. Codex P1 on PR #488.
        session = event["data"]["object"]
        if session.get("metadata", {}).get("purpose") == "credit_top_up":
            put_metric(
                "credit.top_up.payment_failed",
                dimensions={"source": "stripe_checkout"},
            )
            logger.warning(
                "Credit top-up payment failed for session %s (user=%s)",
                session.get("id"),
                session.get("metadata", {}).get("user_id"),
            )

    return {"status": "ok"}
