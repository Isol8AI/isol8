"""Container repository -- DynamoDB operations for the containers table."""

import uuid

from boto3.dynamodb.conditions import Key

from core.dynamodb import get_table, run_in_thread, utc_now_iso


def _get_table():
    return get_table("containers")


async def get_by_user_id(user_id: str) -> dict | None:
    table = _get_table()
    response = await run_in_thread(table.get_item, Key={"user_id": user_id})
    return response.get("Item")


# Alias: owner_id is user_id for personal, org_id for orgs.
# The DynamoDB PK "user_id" holds the owner_id value.
get_by_owner_id = get_by_user_id


async def get_by_gateway_token(token: str) -> dict | None:
    table = _get_table()
    response = await run_in_thread(
        table.query,
        IndexName="gateway-token-index",
        KeyConditionExpression=Key("gateway_token").eq(token),
    )
    items = response.get("Items", [])
    return items[0] if items else None


async def get_by_status(status: str) -> list[dict]:
    table = _get_table()
    response = await run_in_thread(
        table.query,
        IndexName="status-index",
        KeyConditionExpression=Key("status").eq(status),
    )
    return response.get("Items", [])


async def upsert(user_id: str, fields: dict) -> dict:
    """Create or update a container record. Preserves id and created_at on existing items."""
    table = _get_table()
    existing = await get_by_user_id(user_id)

    now = utc_now_iso()
    item = {
        "user_id": user_id,
        "id": existing["id"] if existing else str(uuid.uuid4()),
        "created_at": existing["created_at"] if existing else now,
        "updated_at": now,
        **fields,
    }
    # Ensure user_id is not overridden by fields
    item["user_id"] = user_id

    await run_in_thread(table.put_item, Item=item)
    return item


async def update_status(user_id: str, status: str, substatus: str | None = None) -> dict | None:
    fields = {"status": status, "substatus": substatus}
    return await update_fields(user_id, fields)


async def update_fields(user_id: str, fields: dict) -> dict | None:
    existing = await get_by_user_id(user_id)
    if existing is None:
        return None

    existing.update(fields)
    existing["updated_at"] = utc_now_iso()

    table = _get_table()
    await run_in_thread(table.put_item, Item=existing)
    return existing


async def delete(user_id: str) -> None:
    table = _get_table()
    await run_in_thread(table.delete_item, Key={"user_id": user_id})
