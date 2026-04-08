"""Channel link repository — DynamoDB operations for the channel-links table.

Stores per-member identity links to per-agent channel bots. Primary key is
(owner_id, sk="provider#agent_id#peer_id"). The by-member GSI supports
querying all links for one Clerk member across all their orgs.
"""

from boto3.dynamodb.conditions import Key

from core.dynamodb import get_table, run_in_thread, utc_now_iso


def _get_table():
    return get_table("channel-links")


def _sk(provider: str, agent_id: str, peer_id: str) -> str:
    return f"{provider}#{agent_id}#{peer_id}"


def _owner_provider_agent(owner_id: str, provider: str, agent_id: str) -> str:
    return f"{owner_id}#{provider}#{agent_id}"


async def put(
    *,
    owner_id: str,
    provider: str,
    agent_id: str,
    peer_id: str,
    member_id: str,
    linked_via: str,
) -> dict:
    """Create or overwrite a channel link row."""
    item = {
        "owner_id": owner_id,
        "sk": _sk(provider, agent_id, peer_id),
        "provider": provider,
        "agent_id": agent_id,
        "peer_id": peer_id,
        "member_id": member_id,
        "linked_via": linked_via,
        "linked_at": utc_now_iso(),
        # Denormalized composite for the by-member GSI sort key
        "owner_provider_agent": _owner_provider_agent(owner_id, provider, agent_id),
    }
    table = _get_table()
    await run_in_thread(table.put_item, Item=item)
    return item


async def get_by_peer(
    *,
    owner_id: str,
    provider: str,
    agent_id: str,
    peer_id: str,
) -> dict | None:
    """Look up a single link row by its full primary key."""
    table = _get_table()
    response = await run_in_thread(
        table.get_item,
        Key={"owner_id": owner_id, "sk": _sk(provider, agent_id, peer_id)},
    )
    return response.get("Item")


async def query_by_member(member_id: str) -> list[dict]:
    """Return all link rows for a Clerk member across all orgs.

    Uses the by-member GSI. Does not paginate — acceptable because a
    member is realistically in at most a handful of orgs with a few bots
    each, so the result set fits in a single 1MB query page.
    """
    table = _get_table()
    response = await run_in_thread(
        table.query,
        IndexName="by-member",
        KeyConditionExpression=Key("member_id").eq(member_id),
    )
    return response.get("Items", [])


async def query_by_owner(owner_id: str) -> list[dict]:
    """Return all link rows for a container owner across all providers/agents/peers.

    Uses the main table's hash key directly. Note: does not paginate —
    acceptable because per-owner link counts are small (bounded by number
    of bots × number of members linked).
    """
    table = _get_table()
    response = await run_in_thread(
        table.query,
        KeyConditionExpression=Key("owner_id").eq(owner_id),
    )
    return response.get("Items", [])


async def delete(
    *,
    owner_id: str,
    provider: str,
    agent_id: str,
    peer_id: str,
) -> None:
    """Delete a single link row."""
    table = _get_table()
    await run_in_thread(
        table.delete_item,
        Key={"owner_id": owner_id, "sk": _sk(provider, agent_id, peer_id)},
    )
