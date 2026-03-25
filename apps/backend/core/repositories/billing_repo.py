"""Billing account repository -- DynamoDB operations for the billing_accounts table."""

import uuid
from decimal import Decimal

from boto3.dynamodb.conditions import Key

from core.dynamodb import get_table, run_in_thread, utc_now_iso


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


async def create(
    owner_id: str,
    stripe_customer_id: str,
    plan_tier: str = "free",
    markup_multiplier: float = 1.4,
    owner_type: str = "personal",
) -> dict:
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
    await run_in_thread(table.put_item, Item=item)
    return item


async def get_or_create(
    owner_id: str,
    stripe_customer_id: str,
    plan_tier: str = "free",
    markup_multiplier: float = 1.4,
    owner_type: str = "personal",
) -> dict:
    existing = await get_by_owner_id(owner_id)
    if existing:
        return existing
    return await create(owner_id, stripe_customer_id, plan_tier, markup_multiplier, owner_type=owner_type)


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
