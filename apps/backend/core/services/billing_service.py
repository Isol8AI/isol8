"""Service for Stripe billing operations."""

import logging
import os
import stripe

from core.config import settings
from core.repositories import billing_repo

logger = logging.getLogger(__name__)

# Configure Stripe
stripe.api_key = settings.STRIPE_SECRET_KEY

# Stripe Price IDs per tier.
# Fixed prices differ per tier; metered usage price is shared (same LLM cost).
METERED_PRICE_ID = os.getenv("STRIPE_METERED_PRICE_ID", "")

PLAN_PRICES = {
    "starter": {
        "fixed": os.getenv("STRIPE_STARTER_FIXED_PRICE_ID", ""),
        "metered": METERED_PRICE_ID,
    },
    "pro": {
        "fixed": os.getenv("STRIPE_PRO_FIXED_PRICE_ID", ""),
        "metered": METERED_PRICE_ID,
    },
}

FRONTEND_URL = os.getenv(
    "FRONTEND_URL", settings.cors_origins_list[0] if settings.cors_origins_list else "http://localhost:3000"
)


class BillingServiceError(Exception):
    """Base exception for billing service errors."""

    pass


class BillingService:
    """Manages Stripe customers, subscriptions, and checkout flows."""

    def __init__(self):
        pass

    async def create_customer_for_owner(self, owner_id: str, owner_type: str = "personal", email: str = "") -> dict:
        """Create Stripe customer + billing account for an owner (user or org).

        Idempotent: returns existing account if already created.
        """
        existing = await billing_repo.get_by_owner_id(owner_id)
        if existing:
            return existing

        customer = stripe.Customer.create(
            email=email or None,
            metadata={"owner_id": owner_id, "owner_type": owner_type},
        )

        account = await billing_repo.get_or_create(
            owner_id=owner_id,
            stripe_customer_id=customer.id,
            owner_type=owner_type,
        )
        return account

    async def create_checkout_session(self, billing_account: dict, tier: str) -> str:
        """Create a Stripe Checkout session for subscribing to a plan.

        Returns the checkout URL.
        """
        prices = PLAN_PRICES.get(tier)
        if not prices:
            raise BillingServiceError(f"Unknown tier: {tier}")

        line_items = []
        if prices.get("fixed"):
            line_items.append({"price": prices["fixed"], "quantity": 1})
        if prices.get("metered"):
            line_items.append({"price": prices["metered"]})

        if not line_items:
            raise BillingServiceError(f"No Stripe price IDs configured for tier: {tier}")

        session = stripe.checkout.Session.create(
            customer=billing_account["stripe_customer_id"],
            mode="subscription",
            line_items=line_items,
            subscription_data={"metadata": {"plan_tier": tier}},
            success_url=f"{FRONTEND_URL}/chat?subscription=success",
            cancel_url=f"{FRONTEND_URL}/chat?subscription=canceled",
        )
        return session.url

    async def create_portal_session(self, billing_account: dict) -> str:
        """Create a Stripe Customer Portal session.

        Returns the portal URL for managing payment methods and invoices.
        """
        session = stripe.billing_portal.Session.create(
            customer=billing_account["stripe_customer_id"],
            return_url=f"{FRONTEND_URL}/settings/billing",
        )
        return session.url

    async def update_subscription(self, billing_account: dict, subscription_id: str, tier: str) -> None:
        """Update billing account after subscription change."""
        await billing_repo.update_subscription(
            owner_id=billing_account["owner_id"],
            stripe_subscription_id=subscription_id,
            plan_tier=tier,
        )

    async def cancel_subscription(self, billing_account: dict) -> None:
        """Revert to free tier after subscription cancellation."""
        await billing_repo.update_subscription(
            owner_id=billing_account["owner_id"],
            stripe_subscription_id=None,
            plan_tier="free",
        )
