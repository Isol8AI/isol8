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
    async def create_customer_for_owner(
        self, owner_id: str, owner_type: str = "personal", email: str | None = None
    ) -> dict:
        existing = await billing_repo.get_by_owner_id(owner_id)
        if existing:
            return existing

        # Create the Stripe customer first, then try to claim the DynamoDB
        # slot with a conditional write. If another concurrent call already
        # won the race (webhook + frontend sync fire at the same time), the
        # conditional put raises AlreadyExistsError — we delete the orphan
        # Stripe customer and return the winner's record.
        #
        # This replaces the previous Stripe search approach which was
        # eventually consistent and still produced duplicates within the
        # same second.
        customer = stripe.Customer.create(
            email=email,
            metadata={"owner_id": owner_id, "owner_type": owner_type},
        )

        try:
            return await billing_repo.create_if_not_exists(
                owner_id=owner_id,
                stripe_customer_id=customer.id,
                owner_type=owner_type,
            )
        except billing_repo.AlreadyExistsError:
            # Another call won the race. Delete our orphan Stripe customer
            # and return the winner's record.
            logger.info(
                "Billing account race: owner_id=%s already exists, deleting orphan Stripe customer %s",
                owner_id,
                customer.id,
            )
            try:
                stripe.Customer.delete(customer.id)
            except Exception:
                logger.warning("Failed to delete orphan Stripe customer %s", customer.id)
            return await billing_repo.get_by_owner_id(owner_id)

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
