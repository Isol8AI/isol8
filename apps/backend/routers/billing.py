"""Billing API endpoints with ECS Fargate container provisioning."""

import asyncio
import logging
from datetime import date

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request

from core.auth import AuthContext, get_current_user, resolve_owner_id, get_owner_type
from core.config import settings, TIER_CONFIG
from core.containers import get_ecs_manager
from core.containers.ecs_manager import EcsManagerError
from core.containers.workspace import WorkspaceError
from core.repositories import billing_repo
from core.services.billing_service import BillingService
from schemas.billing import (
    BillingAccountResponse,
    CheckoutRequest,
    CheckoutResponse,
    PortalResponse,
    UsagePeriod,
    UsageResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


async def _get_billing_account(auth: AuthContext) -> dict | None:
    """Resolve billing account from auth context."""
    return await billing_repo.get_by_owner_id(resolve_owner_id(auth))


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
):
    account = await _get_billing_account(auth)
    if not account:
        # Auto-create for users who signed up before billing existed
        billing_service = BillingService()
        owner_id = resolve_owner_id(auth)
        owner_type = get_owner_type(auth)
        account = await billing_service.create_customer_for_owner(owner_id=owner_id, owner_type=owner_type)

    tier = TIER_CONFIG.get(account.get("plan_tier", "free"), TIER_CONFIG["free"])
    budget = tier["included_budget_microdollars"]
    budget_dollars = budget / 1_000_000

    # Usage tracking is not yet migrated to DynamoDB; return zero usage for now
    monthly_dollars = 0
    overage = 0
    percent = 0

    today = date.today()
    period_start = today.replace(day=1)
    if today.month == 12:
        period_end = today.replace(year=today.year + 1, month=1, day=1)
    else:
        period_end = today.replace(month=today.month + 1, day=1)

    return BillingAccountResponse(
        plan_tier=account.get("plan_tier", "free"),
        has_subscription=account.get("stripe_subscription_id") is not None,
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
):
    account = await _get_billing_account(auth)
    if not account:
        raise HTTPException(status_code=404, detail="Billing account not found")

    # Usage tracking stubbed out — return empty data
    return UsageResponse(period=None, total_cost=0, total_requests=0, by_model=[], by_day=[])


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
):
    billing_service = BillingService()
    account = await _get_billing_account(auth)
    if not account:
        # Auto-create billing account for users who signed up before billing existed
        owner_id = resolve_owner_id(auth)
        owner_type = get_owner_type(auth)
        account = await billing_service.create_customer_for_owner(owner_id=owner_id, owner_type=owner_type)

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
):
    account = await _get_billing_account(auth)
    if not account:
        raise HTTPException(status_code=404, detail="Billing account not found")

    billing_service = BillingService()
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

    billing_service = BillingService()

    if event_type == "customer.subscription.created":
        customer_id = event_data["customer"]
        subscription_id = event_data["id"]
        tier = event_data.get("metadata", {}).get("plan_tier", "starter")

        # GSI lookup — retry once if eventual consistency returns None
        account = await billing_repo.get_by_stripe_customer_id(customer_id)
        if account is None:
            await asyncio.sleep(1)
            account = await billing_repo.get_by_stripe_customer_id(customer_id)

        if account:
            await billing_service.update_subscription(account, subscription_id, tier)

            # Provision ECS Service for subscriber
            try:
                owner_id = account["owner_id"]
                owner_type = account.get("owner_type", "personal")
                service_name = await get_ecs_manager().provision_user_container(owner_id, owner_type=owner_type)
                logger.info("ECS service %s provisioned for owner %s (tier=%s)", service_name, owner_id, tier)
            except (EcsManagerError, WorkspaceError) as e:
                logger.error("Failed to provision ECS service for owner %s: %s", account["owner_id"], e)

    elif event_type == "customer.subscription.updated":
        customer_id = event_data["customer"]
        tier = event_data.get("metadata", {}).get("plan_tier", "starter")

        account = await billing_repo.get_by_stripe_customer_id(customer_id)
        if account is None:
            await asyncio.sleep(1)
            account = await billing_repo.get_by_stripe_customer_id(customer_id)

        if account:
            await billing_service.update_subscription(account, event_data["id"], tier)

    elif event_type == "customer.subscription.deleted":
        customer_id = event_data["customer"]

        account = await billing_repo.get_by_stripe_customer_id(customer_id)
        if account is None:
            await asyncio.sleep(1)
            account = await billing_repo.get_by_stripe_customer_id(customer_id)

        if account:
            await billing_service.cancel_subscription(account)

            # Stop ECS Service (EFS volume preserved for 30-day grace period)
            try:
                await get_ecs_manager().stop_user_service(account["owner_id"])
                logger.info("ECS service stopped for owner %s (subscription cancelled)", account["owner_id"])
            except EcsManagerError as e:
                logger.error("Failed to stop ECS service for owner %s: %s", account["owner_id"], e)

    elif event_type == "invoice.payment_failed":
        logger.warning("Payment failed for customer %s", event_data.get("customer"))

    elif event_type == "invoice.paid":
        logger.info("Payment succeeded for customer %s", event_data.get("customer"))

    return {"status": "ok"}
