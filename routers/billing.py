"""Billing API endpoints with ECS Fargate container provisioning."""

import logging
import secrets
from datetime import date

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import AuthContext, get_current_user
from core.config import settings, PLAN_BUDGETS
from core.containers import get_ecs_manager, get_workspace
from core.containers.config import write_mcporter_config, write_openclaw_config, write_paired_devices_config
from core.containers.device_identity import generate_device_identity
from core.containers.ecs_manager import EcsManagerError
from core.containers.workspace import WorkspaceError
from core.database import get_db
from core.services.billing_service import BillingService
from core.services.usage_service import UsageService
from models.billing import BillingAccount
from models.container import Container
from schemas.billing import (
    BillingAccountResponse,
    CheckoutRequest,
    CheckoutResponse,
    PortalResponse,
    UsagePeriod,
    UsageResponse,
    ModelUsage,
    DailyUsage,
)

logger = logging.getLogger(__name__)

router = APIRouter()


async def _get_billing_account(auth: AuthContext, db: AsyncSession) -> BillingAccount:
    """Resolve billing account from auth context."""
    usage_service = UsageService(db)
    return await usage_service.get_billing_account_for_user(auth.user_id)


@router.get(
    "/account",
    response_model=BillingAccountResponse,
    summary="Get billing account",
    description="Returns billing account details and current period usage summary.",
    operation_id="get_billing_account",
    responses={404: {"description": "Billing account not found"}},
)
async def get_billing_account(
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    account = await _get_billing_account(auth, db)
    if not account:
        # Auto-create for users who signed up before billing existed
        billing_service = BillingService(db)
        account = await billing_service.create_customer_for_user(clerk_user_id=auth.user_id, email="")

    usage_service = UsageService(db)
    monthly_microdollars = await usage_service.get_monthly_billable(account.id)
    monthly_dollars = monthly_microdollars / 1_000_000

    budget = PLAN_BUDGETS.get(account.plan_tier, 0)
    budget_dollars = budget / 1_000_000
    overage = max(0, monthly_dollars - budget_dollars) if budget_dollars > 0 else 0
    percent = (monthly_dollars / budget_dollars * 100) if budget_dollars > 0 else 0

    today = date.today()
    period_start = today.replace(day=1)
    if today.month == 12:
        period_end = today.replace(year=today.year + 1, month=1, day=1)
    else:
        period_end = today.replace(month=today.month + 1, day=1)

    return BillingAccountResponse(
        plan_tier=account.plan_tier,
        has_subscription=account.stripe_subscription_id is not None,
        current_period=UsagePeriod(
            start=period_start,
            end=period_end,
            included_budget=budget_dollars,
            used=monthly_dollars,
            overage=overage,
            percent_used=round(percent, 1),
        ),
    )


@router.get(
    "/usage",
    response_model=UsageResponse,
    summary="Get usage breakdown",
    description="Returns current period usage breakdown by model and day.",
    operation_id="get_usage",
    responses={404: {"description": "Billing account not found"}},
)
async def get_usage(
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    account = await _get_billing_account(auth, db)
    if not account:
        raise HTTPException(status_code=404, detail="Billing account not found")

    usage_service = UsageService(db)
    breakdown = await usage_service.get_usage_breakdown(account.id)

    today = date.today()
    period_start = today.replace(day=1)
    if today.month == 12:
        period_end = today.replace(year=today.year + 1, month=1, day=1)
    else:
        period_end = today.replace(month=today.month + 1, day=1)

    budget = PLAN_BUDGETS.get(account.plan_tier, 0)
    budget_dollars = budget / 1_000_000
    used = breakdown["total_cost"]
    overage = max(0, used - budget_dollars) if budget_dollars > 0 else 0
    percent = (used / budget_dollars * 100) if budget_dollars > 0 else 0

    return UsageResponse(
        period=UsagePeriod(
            start=period_start,
            end=period_end,
            included_budget=budget_dollars,
            used=used,
            overage=overage,
            percent_used=round(percent, 1),
        ),
        total_cost=breakdown["total_cost"],
        total_requests=breakdown["total_requests"],
        by_model=[ModelUsage(**m) for m in breakdown["by_model"]],
        by_day=[DailyUsage(**d) for d in breakdown["by_day"]],
    )


@router.post(
    "/checkout",
    response_model=CheckoutResponse,
    summary="Create checkout session",
    description="Creates a Stripe Checkout session to subscribe to a plan.",
    operation_id="create_checkout",
    responses={404: {"description": "Billing account not found"}},
)
async def create_checkout(
    request: CheckoutRequest,
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    billing_service = BillingService(db)
    account = await _get_billing_account(auth, db)
    if not account:
        # Auto-create billing account for users who signed up before billing existed
        account = await billing_service.create_customer_for_user(clerk_user_id=auth.user_id, email="")

    url = await billing_service.create_checkout_session(account, request.tier.value)
    return CheckoutResponse(checkout_url=url)


@router.post(
    "/portal",
    response_model=PortalResponse,
    summary="Create customer portal session",
    description="Creates a Stripe Customer Portal session for payment management.",
    operation_id="create_portal",
    responses={404: {"description": "Billing account not found"}},
)
async def create_portal(
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    account = await _get_billing_account(auth, db)
    if not account:
        raise HTTPException(status_code=404, detail="Billing account not found")

    billing_service = BillingService(db)
    url = await billing_service.create_portal_session(account)
    return PortalResponse(portal_url=url)


@router.post(
    "/webhooks/stripe",
    summary="Handle Stripe webhooks",
    description="Processes Stripe webhook events for subscription lifecycle.",
    operation_id="handle_stripe_webhook",
    include_in_schema=False,
)
async def handle_stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Handle Stripe webhook events. No Clerk auth — uses Stripe signature."""
    body = await request.body()
    sig = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(body, sig, settings.STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        logger.error("Stripe webhook signature verification failed: %s", e)
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = event["type"]
    event_data = event["data"]["object"]

    billing_service = BillingService(db)

    if event_type == "customer.subscription.created":
        customer_id = event_data["customer"]
        subscription_id = event_data["id"]
        tier = event_data.get("metadata", {}).get("plan_tier", "starter")

        result = await db.execute(select(BillingAccount).where(BillingAccount.stripe_customer_id == customer_id))
        account = result.scalar_one_or_none()
        if account:
            await billing_service.update_subscription(account, subscription_id, tier)

            # Provision ECS Service for subscriber
            try:
                user_id = account.clerk_user_id
                gateway_token = secrets.token_urlsafe(32)

                # Step 1: Create ECS service (desiredCount=0) — creates the
                # per-user EFS access point and directory, but does NOT start
                # the container yet.
                service_name = await get_ecs_manager().create_user_service(user_id, gateway_token, db)

                # Step 2: Generate device identity and write all configs to
                # EFS BEFORE the container boots, so paired.json is in place
                # when OpenClaw starts.
                identity = generate_device_identity()
                container_result = await db.execute(select(Container).where(Container.user_id == user_id))
                container_row = container_result.scalar_one_or_none()
                if container_row:
                    container_row.device_private_key_pem = identity["private_key_pem"]
                    await db.commit()

                config_json = write_openclaw_config(
                    region=settings.AWS_REGION,
                    gateway_token=gateway_token,
                    proxy_base_url=settings.PROXY_BASE_URL,
                )
                get_workspace().write_file(user_id, "devices/paired.json", write_paired_devices_config(identity))
                get_workspace().write_file(user_id, "openclaw.json", config_json)
                get_workspace().write_file(user_id, ".mcporter/mcporter.json", write_mcporter_config())

                # Step 3: Now start the container — configs are on EFS.
                await get_ecs_manager().start_user_service(user_id, db)

                logger.info("ECS service %s provisioned for user %s (tier=%s)", service_name, user_id, tier)
            except (EcsManagerError, WorkspaceError) as e:
                logger.error("Failed to provision ECS service for user %s: %s", account.clerk_user_id, e)

    elif event_type == "customer.subscription.updated":
        customer_id = event_data["customer"]
        tier = event_data.get("metadata", {}).get("plan_tier", "starter")

        result = await db.execute(select(BillingAccount).where(BillingAccount.stripe_customer_id == customer_id))
        account = result.scalar_one_or_none()
        if account:
            await billing_service.update_subscription(account, event_data["id"], tier)

    elif event_type == "customer.subscription.deleted":
        customer_id = event_data["customer"]

        result = await db.execute(select(BillingAccount).where(BillingAccount.stripe_customer_id == customer_id))
        account = result.scalar_one_or_none()
        if account:
            await billing_service.cancel_subscription(account)

            # Stop ECS Service (EFS volume preserved for 30-day grace period)
            try:
                await get_ecs_manager().stop_user_service(account.clerk_user_id, db)
                logger.info("ECS service stopped for user %s (subscription cancelled)", account.clerk_user_id)
            except EcsManagerError as e:
                logger.error("Failed to stop ECS service for user %s: %s", account.clerk_user_id, e)

    elif event_type == "invoice.payment_failed":
        logger.warning("Payment failed for customer %s", event_data.get("customer"))

    elif event_type == "invoice.paid":
        logger.info("Payment succeeded for customer %s", event_data.get("customer"))

    return {"status": "ok"}
