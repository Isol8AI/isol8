"""Service for Stripe billing operations — hybrid tier model."""

import logging
import os

import stripe

from core.config import settings
from core.repositories import billing_repo

logger = logging.getLogger(__name__)

stripe.api_key = settings.STRIPE_SECRET_KEY

METERED_PRICE_ID = os.getenv("STRIPE_METERED_PRICE_ID", "")

TIER_PRICES = {
    "starter": os.getenv("STRIPE_STARTER_PRICE_ID", ""),
    "pro": os.getenv("STRIPE_PRO_PRICE_ID", ""),
    "enterprise": os.getenv("STRIPE_ENTERPRISE_PRICE_ID", ""),
}

FRONTEND_URL = os.getenv(
    "FRONTEND_URL", settings.cors_origins_list[0] if settings.cors_origins_list else "http://localhost:3000"
)


class BillingServiceError(Exception):
    pass


class BillingService:
    async def create_customer_for_owner(self, owner_id: str, owner_type: str = "personal", email: str = "") -> dict:
        existing = await billing_repo.get_by_owner_id(owner_id)
        if existing:
            return existing

        # Before creating a new Stripe customer, search Stripe for an existing one
        # with matching metadata.owner_id. This prevents duplicate customer creation
        # when concurrent /users/sync calls all miss the DynamoDB row at the same time.
        # Note: Stripe search is eventually consistent, so a customer created <1s ago
        # may not show up. That's OK — billing_repo.get_or_create handles the DB race.
        customer_id: str | None = None
        try:
            search_result = stripe.Customer.search(
                query=f"metadata['owner_id']:'{owner_id}'",
                limit=2,
            )
            matches = list(getattr(search_result, "data", []) or [])
            if len(matches) == 1:
                customer_id = matches[0].id
                logger.info("Reusing existing Stripe customer for owner_id=%s (%s)", owner_id, customer_id)
            elif len(matches) > 1:
                # Pick the oldest (smallest `created` timestamp). Leave cleanup to an admin tool.
                oldest = min(matches, key=lambda c: getattr(c, "created", 0) or 0)
                customer_id = oldest.id
                logger.warning(
                    "Found %d orphan Stripe customers for owner_id=%s; reusing oldest (%s)",
                    len(matches),
                    owner_id,
                    customer_id,
                )
        except Exception as e:
            # Search API may be disabled on the account, rate-limited, or transiently
            # unavailable. Never block provisioning — fall through to Customer.create.
            logger.warning("Stripe customer search failed for owner_id=%s: %s; falling back to create", owner_id, e)

        if customer_id is None:
            customer = stripe.Customer.create(
                email=email or None,
                metadata={"owner_id": owner_id, "owner_type": owner_type},
            )
            customer_id = customer.id

        return await billing_repo.get_or_create(
            owner_id=owner_id,
            stripe_customer_id=customer_id,
            owner_type=owner_type,
        )

    async def create_checkout_session(self, billing_account: dict, tier: str) -> str:
        fixed_price = TIER_PRICES.get(tier)
        if not fixed_price:
            raise BillingServiceError(f"Unknown tier: {tier}")

        line_items = [{"price": fixed_price, "quantity": 1}]
        if METERED_PRICE_ID:
            line_items.append({"price": METERED_PRICE_ID})

        session = stripe.checkout.Session.create(
            customer=billing_account["stripe_customer_id"],
            mode="subscription",
            line_items=line_items,
            subscription_data={"metadata": {"plan_tier": tier}},
            allow_promotion_codes=True,
            success_url=f"{FRONTEND_URL}/chat?subscription=success",
            cancel_url=f"{FRONTEND_URL}/chat?subscription=canceled",
        )
        return session.url

    async def create_portal_session(self, billing_account: dict) -> str:
        session = stripe.billing_portal.Session.create(
            customer=billing_account["stripe_customer_id"],
            return_url=f"{FRONTEND_URL}/settings/billing",
        )
        return session.url

    async def update_subscription(self, billing_account: dict, subscription_id: str, tier: str) -> None:
        await billing_repo.update_subscription(
            owner_id=billing_account["owner_id"],
            stripe_subscription_id=subscription_id,
            plan_tier=tier,
        )

    async def cancel_subscription(self, billing_account: dict) -> None:
        await billing_repo.update_subscription(
            owner_id=billing_account["owner_id"],
            stripe_subscription_id=None,
            plan_tier="free",
        )
        # Disable overage on cancellation
        await billing_repo.set_overage_enabled(billing_account["owner_id"], False)
