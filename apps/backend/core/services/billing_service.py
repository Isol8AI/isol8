"""Service for Stripe billing operations — hybrid tier model."""

import logging
import os

import stripe

from core.config import settings
from core.observability.metrics import put_metric, timing
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


class AlreadySubscribedError(BillingServiceError):
    """Raised when a checkout is attempted while an active Stripe sub exists.

    Why: each successful Stripe Checkout in subscription mode creates a fresh
    sub on the customer. Without this guard, repeated Subscribe clicks pile up
    duplicate subs that all keep billing — incident 2026-04-17.
    """


# Stripe sub statuses that should block a new checkout — i.e. the customer
# already has a sub that is currently being served or in active dunning.
#
# Intentionally NOT in this set:
#   - `incomplete` / `incomplete_expired`: initial payment never completed,
#      so user must be allowed to retry — blocking would strand conversion.
#   - `unpaid`: terminal dunning, sub is suspended; user retry should be
#      permitted so they can re-subscribe without first canceling the dead row.
#   - `canceled`: explicit cancellation, retry is the intent.
_BLOCKING_SUB_STATUSES = frozenset({"active", "trialing", "past_due"})


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
        with timing("stripe.api.latency", {"op": "customers.create"}):
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
                with timing("stripe.api.latency", {"op": "customers.delete"}):
                    stripe.Customer.delete(customer.id)
            except Exception:
                put_metric("stripe.api.error", dimensions={"op": "customers.delete", "error_code": "unknown"})
                logger.warning("Failed to delete orphan Stripe customer %s", customer.id)
            return await billing_repo.get_by_owner_id(owner_id)

    async def create_checkout_session(self, billing_account: dict, tier: str) -> str:
        fixed_price = TIER_PRICES.get(tier)
        if not fixed_price:
            raise BillingServiceError(f"Unknown tier: {tier}")

        # Refuse to create a second sub when one is already active.
        # Self-heal: if DDB's stored sub_id no longer exists in Stripe (lost
        # cancellation webhook), proceed and let the new sub take over.
        sub_id = billing_account.get("stripe_subscription_id")
        if sub_id:
            try:
                with timing("stripe.api.latency", {"op": "subscription.retrieve"}):
                    sub = stripe.Subscription.retrieve(sub_id)
            except stripe.error.InvalidRequestError as e:
                # Only treat "resource missing" as self-heal — other invalid-request
                # errors (malformed id, account mismatch, etc.) shouldn't bypass
                # the duplicate-sub guard.
                if getattr(e, "code", None) != "resource_missing":
                    raise
                logger.info(
                    "Stored sub %s not found in Stripe for owner %s — proceeding with new checkout",
                    sub_id,
                    billing_account.get("owner_id"),
                )
            else:
                if sub.get("status") in _BLOCKING_SUB_STATUSES:
                    raise AlreadySubscribedError(
                        f"Customer already has subscription {sub_id} (status={sub.get('status')})"
                    )

        # Initial subscription includes ONLY the fixed-price tier line item.
        # The metered overage line item (STRIPE_METERED_PRICE_ID) is attached
        # later, and only if the user explicitly opts in via PUT /billing/overage.
        # See `set_metered_overage_item` below.
        #
        # This keeps the Stripe Checkout page clean (one line item, one price)
        # and prevents the confusing "you're subscribing to Starter AND 1 more"
        # display where the metered item appears as a second product.
        line_items = [{"price": fixed_price, "quantity": 1}]

        with timing("stripe.api.latency", {"op": "checkout.session.create"}):
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

    async def set_metered_overage_item(self, billing_account: dict, enabled: bool) -> None:
        """Attach or detach the metered overage line item on the user's active
        Stripe subscription.

        Called from PUT /billing/overage when the user toggles the overage
        setting. Idempotent — if the line item is already in the desired state,
        no Stripe write happens beyond the lookup.

        Raises:
            BillingServiceError: when the account has no active subscription
                (free tier or canceled), or when STRIPE_METERED_PRICE_ID is
                unconfigured. Caller is expected to surface this as a 400.
        """
        if not METERED_PRICE_ID:
            raise BillingServiceError("Metered price ID not configured")

        sub_id = billing_account.get("stripe_subscription_id")
        if not sub_id:
            raise BillingServiceError("No active subscription to modify")

        subscription = stripe.Subscription.retrieve(sub_id)
        existing_metered_item = None
        for item in subscription["items"]["data"]:
            if item["price"]["id"] == METERED_PRICE_ID:
                existing_metered_item = item
                break

        if enabled and existing_metered_item is None:
            # Add the metered line item to the existing subscription. The
            # user's card auth from initial checkout covers this — Stripe
            # doesn't require a new authorization to add a metered usage
            # component.
            stripe.Subscription.modify(
                sub_id,
                items=[{"price": METERED_PRICE_ID}],
            )
        elif not enabled and existing_metered_item is not None:
            # Remove the metered line item. Stripe's `deleted: true` flag on
            # an existing item id removes that item without affecting the
            # rest of the subscription.
            stripe.Subscription.modify(
                sub_id,
                items=[{"id": existing_metered_item["id"], "deleted": True}],
            )
        # else: already in the desired state — no-op.

    async def create_portal_session(self, billing_account: dict) -> str:
        with timing("stripe.api.latency", {"op": "billing_portal.session.create"}):
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
