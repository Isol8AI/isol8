"""User repository -- DynamoDB operations for the users table."""

from core.dynamodb import get_table, utc_now_iso
from core.services.dynamodb_helper import call_with_metrics

_TABLE_SHORT = "users"


def _get_table():
    return get_table(_TABLE_SHORT)


async def get(user_id: str) -> dict | None:
    table = _get_table()
    response = await call_with_metrics(table.name, "get", table.get_item, Key={"user_id": user_id})
    return response.get("Item")


async def put(user_id: str) -> dict:
    table = _get_table()
    item = {"user_id": user_id, "created_at": utc_now_iso()}
    await call_with_metrics(table.name, "put", table.put_item, Item=item)
    return item


async def delete(user_id: str) -> None:
    table = _get_table()
    await call_with_metrics(table.name, "delete", table.delete_item, Key={"user_id": user_id})
