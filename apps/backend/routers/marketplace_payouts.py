"""Stripe Connect Express onboarding + dashboard endpoints."""

from typing import Annotated

import boto3
import stripe
from fastapi import APIRouter, Depends

from core.auth import AuthContext, get_current_user
from core.config import settings
from core.services import payout_service


router = APIRouter(prefix="/api/v1/marketplace/payouts", tags=["marketplace-payouts"])


def _payout_accounts_table():
    return boto3.resource("dynamodb").Table(settings.MARKETPLACE_PAYOUT_ACCOUNTS_TABLE)


@router.post("/onboard")
async def onboard(auth: Annotated[AuthContext, Depends(get_current_user)]):
    """Get an onboarding link. Creates a Connect account if absent.

    Guards against the create_connect_account 24h-idempotency-window trap:
    re-uses the seller's existing Stripe account_id from DDB if any, instead
    of relying on Stripe-side idempotency.
    """
    table = _payout_accounts_table()
    resp = table.get_item(Key={"seller_id": auth.user_id})
    pa = resp.get("Item", {}) or {}
    account_id = pa.get("stripe_connect_account_id")
    if not account_id:
        account_id = await payout_service.create_connect_account(
            seller_id=auth.user_id, email=auth.email or "", country="US"
        )
        table.put_item(
            Item={
                "seller_id": auth.user_id,
                "stripe_connect_account_id": account_id,
                "onboarding_status": "started",
                "balance_held_cents": pa.get("balance_held_cents", 0),
                "lifetime_earned_cents": pa.get("lifetime_earned_cents", 0),
            }
        )

    url = await payout_service.create_onboarding_link(
        connect_account_id=account_id,
        refresh_url=settings.STRIPE_CONNECT_REFRESH_URL,
        return_url=settings.STRIPE_CONNECT_RETURN_URL,
    )
    return {"onboarding_url": url}


@router.get("/dashboard")
async def dashboard(auth: Annotated[AuthContext, Depends(get_current_user)]):
    """Stripe-hosted dashboard link + held-balance snapshot."""
    table = _payout_accounts_table()
    resp = table.get_item(Key={"seller_id": auth.user_id})
    pa = resp.get("Item", {}) or {}
    account_id = pa.get("stripe_connect_account_id")
    if not account_id:
        return {"dashboard_url": None, "balance_held_cents": 0}
    stripe.api_key = settings.STRIPE_SECRET_KEY
    link = stripe.Account.create_login_link(account_id)
    return {
        "dashboard_url": link.url,
        "balance_held_cents": pa.get("balance_held_cents", 0),
        "lifetime_earned_cents": pa.get("lifetime_earned_cents", 0),
    }
