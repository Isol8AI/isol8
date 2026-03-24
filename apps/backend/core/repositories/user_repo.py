"""User repository -- DynamoDB operations for the users table."""

from core.dynamodb import get_table, run_in_thread, utc_now_iso


def _get_table():
    return get_table("users")


async def get(user_id: str) -> dict | None:
    table = _get_table()
    response = await run_in_thread(table.get_item, Key={"user_id": user_id})
    return response.get("Item")


async def put(user_id: str) -> dict:
    table = _get_table()
    item = {"user_id": user_id, "created_at": utc_now_iso()}
    await run_in_thread(table.put_item, Item=item)
    return item


async def delete(user_id: str) -> None:
    table = _get_table()
    await run_in_thread(table.delete_item, Key={"user_id": user_id})
