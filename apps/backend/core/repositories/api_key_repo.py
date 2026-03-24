"""API key repository -- DynamoDB operations for the api-keys table.

Composite key: PK=user_id, SK=tool_id.
"""

from boto3.dynamodb.conditions import Key

from core.dynamodb import get_table, run_in_thread, utc_now_iso


def _get_table():
    return get_table("api-keys")


async def get_key(user_id: str, tool_id: str) -> dict | None:
    table = _get_table()
    response = await run_in_thread(
        table.get_item,
        Key={"user_id": user_id, "tool_id": tool_id},
    )
    return response.get("Item")


async def set_key(user_id: str, tool_id: str, encrypted_key: str) -> dict:
    table = _get_table()
    now = utc_now_iso()
    item = {
        "user_id": user_id,
        "tool_id": tool_id,
        "encrypted_key": encrypted_key,
        "created_at": now,
        "updated_at": now,
    }
    await run_in_thread(table.put_item, Item=item)
    return item


async def list_keys(user_id: str) -> list[dict]:
    """List all keys for a user, excluding encrypted_key from results."""
    table = _get_table()
    response = await run_in_thread(
        table.query,
        KeyConditionExpression=Key("user_id").eq(user_id),
        ProjectionExpression="user_id, tool_id, created_at, updated_at",
    )
    return response.get("Items", [])


async def delete_key(user_id: str, tool_id: str) -> bool:
    """Delete a key. Returns True if the key existed, False otherwise."""
    existing = await get_key(user_id, tool_id)
    if existing is None:
        return False

    table = _get_table()
    await run_in_thread(
        table.delete_item,
        Key={"user_id": user_id, "tool_id": tool_id},
    )
    return True
