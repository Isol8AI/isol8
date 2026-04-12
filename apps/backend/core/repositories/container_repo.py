"""Container repository -- DynamoDB operations for the containers table."""

import uuid

from boto3.dynamodb.conditions import Key

from core.dynamodb import get_table, utc_now_iso
from core.services.dynamodb_helper import call_with_metrics

_TABLE_SHORT = "containers"


def _get_table():
    return get_table(_TABLE_SHORT)


async def get_by_owner_id(owner_id: str) -> dict | None:
    table = _get_table()
    response = await call_with_metrics(table.name, "get", table.get_item, Key={"owner_id": owner_id})
    return response.get("Item")


async def get_by_gateway_token(token: str) -> dict | None:
    table = _get_table()
    response = await call_with_metrics(
        table.name,
        "query",
        table.query,
        IndexName="gateway-token-index",
        KeyConditionExpression=Key("gateway_token").eq(token),
    )
    items = response.get("Items", [])
    return items[0] if items else None


async def get_by_status(status: str) -> list[dict]:
    table = _get_table()
    response = await call_with_metrics(
        table.name,
        "query",
        table.query,
        IndexName="status-index",
        KeyConditionExpression=Key("status").eq(status),
    )
    return response.get("Items", [])


async def upsert(owner_id: str, fields: dict) -> dict:
    """Create or update a container record. Preserves id and created_at on existing items."""
    table = _get_table()
    existing = await get_by_owner_id(owner_id)

    now = utc_now_iso()
    item = {
        "owner_id": owner_id,
        "id": existing["id"] if existing else str(uuid.uuid4()),
        "created_at": existing["created_at"] if existing else now,
        "updated_at": now,
        **fields,
    }
    # Ensure owner_id is not overridden by fields
    item["owner_id"] = owner_id

    await call_with_metrics(table.name, "put", table.put_item, Item=item)
    return item


async def update_status(owner_id: str, status: str, substatus: str | None = None) -> dict | None:
    fields = {"status": status, "substatus": substatus}
    return await update_fields(owner_id, fields)


async def update_fields(owner_id: str, fields: dict) -> dict | None:
    existing = await get_by_owner_id(owner_id)
    if existing is None:
        return None

    existing.update(fields)
    existing["updated_at"] = utc_now_iso()

    table = _get_table()
    await call_with_metrics(table.name, "put", table.put_item, Item=existing)
    return existing


async def update_error(owner_id: str, error: str) -> dict | None:
    """Record the last error for a container."""
    return await update_fields(
        owner_id,
        {
            "last_error": error,
            "last_error_at": utc_now_iso(),
        },
    )


async def delete(owner_id: str) -> None:
    table = _get_table()
    await call_with_metrics(table.name, "delete", table.delete_item, Key={"owner_id": owner_id})
