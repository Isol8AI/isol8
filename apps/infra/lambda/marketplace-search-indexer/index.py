"""Marketplace search-index refresh Lambda.

Subscribes to the marketplace-listings DDB stream. On INSERT or MODIFY events
for listings whose status is 'published', writes a denormalized row to the
search-index table sharded by uniform-random shard_id (CRC32 to avoid
clustering on UUID prefixes).
"""
import json
import os
import zlib
from typing import Any

import boto3
from botocore.exceptions import ClientError

DDB = boto3.resource("dynamodb")
SEARCH_INDEX_TABLE = os.environ["MARKETPLACE_SEARCH_INDEX_TABLE"]
SHARD_COUNT = 16


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
    """Convert DDB stream NewImage from typed-attribute form to plain dict."""
    out = {}
    for k, v in image.items():
        if "S" in v:
            out[k] = v["S"]
        elif "N" in v:
            try:
                out[k] = int(v["N"])
            except ValueError:
                out[k] = float(v["N"])
        elif "BOOL" in v:
            out[k] = v["BOOL"]
        elif "L" in v:
            out[k] = [_unwrap_ddb_item({"_": x}).get("_") for x in v["L"]]
        elif "SS" in v:
            out[k] = list(v["SS"])
        else:
            # NULL / M / B etc: best-effort raw passthrough.
            out[k] = next(iter(v.values()))
    return out


def handler(event, _context):
    table = DDB.Table(SEARCH_INDEX_TABLE)
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
        try:
            table.put_item(Item=_project_listing(unwrapped))
        except ClientError as e:
            print(json.dumps({
                "level": "error",
                "msg": "search_index_write_failed",
                "listing_id": unwrapped.get("listing_id"),
                "error": str(e),
            }))
    return {"records": len(event.get("Records", []))}
