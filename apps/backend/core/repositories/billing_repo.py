"""Billing account repository -- DynamoDB operations for the billing_accounts table."""

import logging
import uuid
from decimal import Decimal

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from core.dynamodb import get_table, run_in_thread, utc_now_iso

logger = logging.getLogger(__name__)


class AlreadyExistsError(Exception):
    """Raised when a conditional put fails because the item already exists."""


def _get_table():
    return get_table("billing-accounts")


async def get_by_owner_id(owner_id: str) -> dict | None:
    table = _get_table()
    response = await run_in_thread(table.get_item, Key={"owner_id": owner_id})
    return response.get("Item")


async def get_by_stripe_customer_id(stripe_customer_id: str) -> dict | None:
    table = _get_table()
    response = await run_in_thread(
        table.query,
        IndexName="stripe-customer-index",
        KeyConditionExpression=Key("stripe_customer_id").eq(stripe_customer_id),
    )
    items = response.get("Items", [])
    return items[0] if items else None


async def create_if_not_exists(
    owner_id: str,
    stripe_customer_id: str,
    plan_tier: str = "free",
    markup_multiplier: float = 1.4,
    owner_type: str = "personal",
) -> dict:
    """Atomically create a billing account if one doesn't exist for this owner.

    Uses a DynamoDB conditional put (``attribute_not_exists(owner_id)``)
    so that concurrent calls are serialized: exactly one wins, the rest
    raise ``AlreadyExistsError``. This is the single source of truth for
    preventing duplicate Stripe customers — Stripe's search API is
    eventually consistent and can't be trusted for dedup.
    """
    table = _get_table()
    now = utc_now_iso()
    item = {
        "owner_id": owner_id,
        "owner_type": owner_type,
        "id": str(uuid.uuid4()),
        "stripe_customer_id": stripe_customer_id,
        "plan_tier": plan_tier,
        "markup_multiplier": Decimal(str(markup_multiplier)),
        "created_at": now,
        "updated_at": now,
    }
    try:
        await run_in_thread(
            table.put_item,
            Item=item,
            ConditionExpression="attribute_not_exists(owner_id)",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise AlreadyExistsError(owner_id) from e
        raise
    return item


async def update_subscription(
    owner_id: str,
    stripe_subscription_id: str | None,
    plan_tier: str,
) -> dict | None:
    existing = await get_by_owner_id(owner_id)
    if existing is None:
        return None

    existing["stripe_subscription_id"] = stripe_subscription_id
    existing["plan_tier"] = plan_tier
    existing["updated_at"] = utc_now_iso()

    table = _get_table()
    await run_in_thread(table.put_item, Item=existing)
    return existing


async def delete(owner_id: str) -> None:
    table = _get_table()
    await run_in_thread(table.delete_item, Key={"owner_id": owner_id})


async def set_overage_enabled(owner_id: str, enabled: bool, overage_limit: int | None = None) -> dict | None:
    """Toggle overage for the current billing period."""
    existing = await get_by_owner_id(owner_id)
    if existing is None:
        return None

    existing["overage_enabled"] = enabled
    if overage_limit is not None:
        existing["overage_limit"] = Decimal(str(overage_limit))
    elif not enabled:
        existing.pop("overage_limit", None)
    existing["updated_at"] = utc_now_iso()

    table = _get_table()
    await run_in_thread(table.put_item, Item=existing)
    return existing
