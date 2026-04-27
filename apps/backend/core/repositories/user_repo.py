"""User repository -- DynamoDB operations for the users table."""

from core.dynamodb import get_table, run_in_thread, utc_now_iso


def _get_table():
    return get_table("users")


async def get(user_id: str) -> dict | None:
    table = _get_table()
    response = await run_in_thread(table.get_item, Key={"user_id": user_id})
    return response.get("Item")


# Alias for naming uniformity with the other per-user repos (which all
# expose ``get_by_owner_id`` / ``get_by_user_id`` accessors). Used by the
# debug ``/ddb-rows`` teardown-verification endpoint so the call surface
# is consistent across all 8 per-user tables.
get_by_user_id = get


async def put(user_id: str) -> dict:
    table = _get_table()
    item = {"user_id": user_id, "created_at": utc_now_iso()}
    await run_in_thread(table.put_item, Item=item)
    return item


async def delete(user_id: str) -> None:
    table = _get_table()
    await run_in_thread(table.delete_item, Key={"user_id": user_id})


async def set_provider_choice(
    user_id: str,
    *,
    provider_choice: str,
    byo_provider: str | None = None,
) -> None:
    """Persist the user's flat-fee provider selection (Plan 3 Task 3).

    ``provider_choice`` is one of:
      - ``"chatgpt_oauth"``: user signed in with ChatGPT (card 1)
      - ``"byo_key"``: user provided their own OpenAI/Anthropic key (card 2)
      - ``"bedrock_claude"``: we provide Claude via Bedrock (card 3)

    ``byo_provider`` is only meaningful when ``provider_choice == "byo_key"``;
    it identifies which key was saved (``"openai"`` or ``"anthropic"``). For
    other ``provider_choice`` values it's ``None``.

    Used by the gateway (Plan 3 Tasks 4 + 5) to decide whether to gate
    chat on credit balance (card 3 only) and whether to deduct on
    ``chat.final``.
    """
    update_expr = "SET provider_choice = :pc, updated_at = :t"
    values: dict = {":pc": provider_choice, ":t": utc_now_iso()}
    if byo_provider is not None:
        update_expr += ", byo_provider = :bp"
        values[":bp"] = byo_provider

    table = _get_table()
    await run_in_thread(
        table.update_item,
        Key={"user_id": user_id},
        UpdateExpression=update_expr,
        ExpressionAttributeValues=values,
    )
