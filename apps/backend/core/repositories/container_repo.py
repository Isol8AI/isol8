"""Container repository -- DynamoDB operations for the containers table."""

import uuid

from boto3.dynamodb.conditions import Key

from core.dynamodb import get_table, run_in_thread, utc_now_iso


def _get_table():
    return get_table("containers")


async def get_by_owner_id(owner_id: str) -> dict | None:
    table = _get_table()
    response = await run_in_thread(table.get_item, Key={"owner_id": owner_id})
    return response.get("Item")


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

    await run_in_thread(table.put_item, Item=item)
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
    await run_in_thread(table.put_item, Item=existing)
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


async def update_last_active(owner_id: str, iso_ts: str) -> None:
    """Record the last user-activity timestamp on a running container.

    Conditional update: only writes if the row exists AND status != "stopped".
    A ConditionalCheckFailedException is swallowed -- late pings for a stopped
    or deleted row are a no-op, never an error.
    """
    from botocore.exceptions import ClientError

    table = _get_table()
    try:
        await run_in_thread(
            table.update_item,
            Key={"owner_id": owner_id},
            UpdateExpression="SET last_active_at = :t, updated_at = :u",
            ConditionExpression="attribute_exists(owner_id) AND #s <> :stopped",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":t": iso_ts,
                ":u": utc_now_iso(),
                ":stopped": "stopped",
            },
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return
        raise


async def mark_stopped_if_running(owner_id: str) -> bool:
    """Flip status from "running" to "stopped" atomically.

    Returns True if this call performed the transition, False if the row
    was already stopped, missing, or in some other state. Safe for multiple
    concurrent reapers.
    """
    from botocore.exceptions import ClientError

    table = _get_table()
    try:
        await run_in_thread(
            table.update_item,
            Key={"owner_id": owner_id},
            UpdateExpression="SET #s = :stopped, updated_at = :u",
            ConditionExpression="attribute_exists(owner_id) AND #s = :running",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":stopped": "stopped",
                ":running": "running",
                ":u": utc_now_iso(),
            },
        )
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


async def delete(owner_id: str) -> None:
    table = _get_table()
    await run_in_thread(table.delete_item, Key={"owner_id": owner_id})
