"""Marketplace search-index refresh Lambda.

Subscribes to the marketplace-listings DDB stream. On INSERT or MODIFY events
for listings whose status is 'published', writes a denormalized row to the
search-index table sharded by uniform-random shard_id (CRC32 to avoid
clustering on UUID prefixes).
"""
import os
import zlib

import boto3
from boto3.dynamodb.types import TypeDeserializer

DDB = boto3.resource("dynamodb")
SEARCH_INDEX_TABLE = os.environ["MARKETPLACE_SEARCH_INDEX_TABLE"]
SHARD_COUNT = 16

_DESERIALIZER = TypeDeserializer()


def _shard_for(listing_id: str) -> int:
    """Uniform-random shard via CRC32. Avoids clustering on UUID prefix."""
    return zlib.crc32(listing_id.encode("utf-8")) % SHARD_COUNT


def _published_listing_sk(published_at: str, listing_id: str) -> str:
    return f"{published_at}#{listing_id}"


def _project_listing(item: dict) -> dict:
    """Project listing fields needed for search/browse."""
    return {
        "shard_id": _shard_for(item["listing_id"]),
        "published_listing": _published_listing_sk(
            item.get("published_at", ""), item["listing_id"]
        ),
        "listing_id": item["listing_id"],
        "slug": item.get("slug", ""),
        "name": item.get("name", ""),
        "description": item.get("description_md", "")[:500],
        "tags": item.get("tags", []),
        "format": item.get("format", ""),
        "price_cents": item.get("price_cents", 0),
        "seller_id": item.get("seller_id", ""),
    }


def _unwrap_ddb_item(image: dict) -> dict:
    """Convert DDB stream NewImage typed-attribute form to plain dict.

    Uses boto3's canonical TypeDeserializer. Handles all DDB attribute types
    (S, N, B, BOOL, NULL, L, M, SS, NS, BS) correctly.

    Caveat: TypeDeserializer returns ``decimal.Decimal`` for numbers (DDB's
    exact numeric type). The downstream ``put_item`` via the resource API
    accepts ``Decimal`` natively, which is what we want here. If a caller
    ever ``json.dumps()`` the unwrapped dict, ``Decimal`` will not be
    JSON-serializable — wrap with a custom encoder in that case.
    """
    return {k: _DESERIALIZER.deserialize(v) for k, v in image.items()}


def handler(event, _context):
    """Project published listings into the search-index table.

    Idempotent: each (shard_id, published_listing) row gets overwritten on
    every status=published write. When a seller publishes v2 of a listing,
    the new version's projection overwrites v1's. This is intentional —
    search results reflect the latest published version. Plan 2's
    publish_v2 flow guarantees a single LATEST per listing_id at any time.

    Errors from ``put_item`` (throttling, transient failures, etc.) are
    intentionally NOT caught: they propagate so the EventSourceMapping
    retries the batch per its ``retryAttempts`` configuration. Lambda's
    automatic exception logging surfaces failures in CloudWatch.
    """
    table = DDB.Table(SEARCH_INDEX_TABLE)
    indexed = 0
    for record in event.get("Records", []):
        event_name = record["eventName"]
        if event_name not in ("INSERT", "MODIFY"):
            continue
        new = record.get("dynamodb", {}).get("NewImage")
        if not new:
            continue
        unwrapped = _unwrap_ddb_item(new)
        if unwrapped.get("status") != "published":
            continue
        table.put_item(Item=_project_listing(unwrapped))
        indexed += 1
    return {
        "records_processed": len(event.get("Records", [])),
        "records_indexed": indexed,
    }
