"""Marketplace search and browse.

v1: parallel scan across the 16-shard search-index table, in-memory rank by
tag-match-count desc + published_at desc tiebreak. v2 (post-5000-listings or
p99>500ms): swap to OpenSearch behind the same public API.
"""

import asyncio
import time

import boto3

from core.config import settings


SHARD_COUNT = 16


def _search_index_table():
    return boto3.resource("dynamodb").Table(settings.MARKETPLACE_SEARCH_INDEX_TABLE)


async def _scan_shard(shard_id: int) -> list[dict]:
    table = _search_index_table()
    resp = table.scan(
        FilterExpression="shard_id = :s",
        ExpressionAttributeValues={":s": shard_id},
        Limit=200,
    )
    return resp.get("Items", [])


async def _all_listings() -> list[dict]:
    """Parallel scan across all shards. v1 only — replace with OpenSearch later.

    Dedupes by listing_id since each listing lives in exactly one shard, but a
    defensive dedupe also protects against accidental cross-shard writes.
    """
    tasks = [_scan_shard(i) for i in range(SHARD_COUNT)]
    by_shard = await asyncio.gather(*tasks)
    seen: set[str] = set()
    out: list[dict] = []
    for shard in by_shard:
        for item in shard:
            lid = item.get("listing_id")
            if lid in seen:
                continue
            if lid is not None:
                seen.add(lid)
            out.append(item)
    return out


async def browse(*, limit: int = 24) -> list[dict]:
    """Return most-recent-published listings."""
    items = await _all_listings()
    items.sort(key=lambda x: x.get("published_at", ""), reverse=True)
    return items[:limit]


async def search(*, query_tags: list[str], limit: int = 24) -> list[dict]:
    """Search by tag intersection. Rank: tag-match-count desc, then recency desc."""
    if not query_tags:
        return await browse(limit=limit)
    qset = {t.lower().strip() for t in query_tags}
    items = await _all_listings()
    scored: list[tuple[int, str, dict]] = []
    for item in items:
        item_tags = {t.lower().strip() for t in item.get("tags", [])}
        match_count = len(qset & item_tags)
        if match_count == 0:
            continue
        scored.append((match_count, item.get("published_at", ""), item))
    # Higher match_count first; within same match_count, more recent first.
    scored.sort(key=lambda t: (-t[0], -_iso_to_int(t[1])))
    return [t[2] for t in scored[:limit]]


def _iso_to_int(iso: str) -> int:
    if not iso:
        return 0
    try:
        struct = time.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")
        return int(time.mktime(struct))
    except ValueError:
        return 0
