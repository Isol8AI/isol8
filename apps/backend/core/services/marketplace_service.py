"""Marketplace listings service.

Wraps catalog_service for packaging; adds:
  - listing-level metadata (price, seller, status, delivery_method)
  - state machine (draft -> review -> published -> retired/taken_down)
  - v2 publish via DynamoDB TransactWriteItems for atomicity
  - one row per version in the immutable versions table
"""

import hashlib
import json
import time
import uuid

import boto3
from botocore.exceptions import ClientError

from core.config import settings


def _listings_table():
    return boto3.resource("dynamodb").Table(settings.MARKETPLACE_LISTINGS_TABLE)


def _versions_table():
    return boto3.resource("dynamodb").Table(settings.MARKETPLACE_LISTING_VERSIONS_TABLE)


def _dynamodb_client():
    return boto3.client("dynamodb")


class InvalidStateError(Exception):
    """Listing is not in the state required for the operation."""


class SlugCollisionError(Exception):
    """Another listing already owns this slug."""


async def _upload_artifact_to_s3(
    *, listing_id: str, version: int, artifact_bytes: bytes, manifest: dict
) -> tuple[str, str]:
    """Upload tarball + manifest to the marketplace bucket. Returns (s3_prefix, manifest_sha256)."""
    s3 = boto3.client("s3")
    bucket = settings.MARKETPLACE_ARTIFACTS_BUCKET
    prefix = f"listings/{listing_id}/v{version}/"
    s3.put_object(Bucket=bucket, Key=f"{prefix}workspace.tar.gz", Body=artifact_bytes)
    manifest_bytes = json.dumps(manifest, sort_keys=True).encode("utf-8")
    s3.put_object(Bucket=bucket, Key=f"{prefix}manifest.json", Body=manifest_bytes)
    sha = hashlib.sha256(manifest_bytes).hexdigest()
    return prefix, sha


async def create_draft(
    *,
    seller_id: str,
    slug: str,
    name: str,
    description_md: str,
    format: str,
    delivery_method: str,
    price_cents: int,
    tags: list[str],
    artifact_bytes: bytes,
    manifest: dict,
) -> dict:
    """Create a new listing in draft state. Slug must be unique."""
    table = _listings_table()
    existing = table.query(
        IndexName="slug-version-index",
        KeyConditionExpression="slug = :s",
        ExpressionAttributeValues={":s": slug},
        Limit=1,
    )
    if existing.get("Items"):
        raise SlugCollisionError(f"slug '{slug}' is taken")

    listing_id = str(uuid.uuid4())
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    s3_prefix, sha = await _upload_artifact_to_s3(
        listing_id=listing_id, version=1, artifact_bytes=artifact_bytes, manifest=manifest
    )
    item = {
        "listing_id": listing_id,
        "version": 1,
        "slug": slug,
        "name": name,
        "description_md": description_md,
        "format": format,
        "delivery_method": delivery_method,
        "price_cents": price_cents,
        "tags": tags,
        "seller_id": seller_id,
        "status": "draft",
        "s3_prefix": s3_prefix,
        "manifest_sha256": sha,
        "manifest_json": manifest,
        "artifact_format_version": "v1",
        "entitlement_policy": "perpetual",
        "created_at": now_iso,
        "updated_at": now_iso,
        "published_at": None,
    }
    table.put_item(Item=item)
    _versions_table().put_item(
        Item={
            "listing_id": listing_id,
            "version": 1,
            "s3_prefix": s3_prefix,
            "manifest_json": manifest,
            "manifest_sha256": sha,
            "published_at": None,
            "published_by": None,
            "changelog_md": "",
            "breaking_change": False,
        }
    )
    return item


async def submit_for_review(*, listing_id: str, seller_id: str) -> dict:
    """Transition draft -> review. Idempotent: re-submitting from review is rejected."""
    table = _listings_table()
    try:
        resp = table.update_item(
            Key={"listing_id": listing_id, "version": 1},
            UpdateExpression="SET #s = :review, updated_at = :now",
            ConditionExpression="seller_id = :sid AND #s = :draft",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":sid": seller_id,
                ":draft": "draft",
                ":review": "review",
                ":now": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
            ReturnValues="ALL_NEW",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise InvalidStateError("listing is not in 'draft' state or you are not the seller")
        raise
    return resp.get("Attributes", {})


async def approve(*, listing_id: str, version: int, approved_by: str) -> dict:
    """Admin transition: review -> published. Sets published_at."""
    table = _listings_table()
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        resp = table.update_item(
            Key={"listing_id": listing_id, "version": version},
            UpdateExpression="SET #s = :pub, published_at = :now, updated_at = :now",
            ConditionExpression="#s = :review",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":review": "review",
                ":pub": "published",
                ":now": now_iso,
            },
            ReturnValues="ALL_NEW",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise InvalidStateError(f"listing v{version} is not in 'review' state")
        raise
    _versions_table().update_item(
        Key={"listing_id": listing_id, "version": version},
        UpdateExpression="SET published_at = :now, published_by = :by",
        ExpressionAttributeValues={":now": now_iso, ":by": approved_by},
    )
    return resp.get("Attributes", {})


async def reject(*, listing_id: str, version: int, notes: str, rejected_by: str) -> dict:
    """Admin transition: review -> draft with rejection notes."""
    table = _listings_table()
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    table.update_item(
        Key={"listing_id": listing_id, "version": version},
        UpdateExpression=(
            "SET #s = :draft,     rejection_notes = :notes,     rejected_by = :by,     updated_at = :now"
        ),
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":draft": "draft",
            ":notes": notes,
            ":by": rejected_by,
            ":now": now_iso,
        },
    )
    return {"status": "draft", "rejection_notes": notes}


async def publish_v2(
    *,
    listing_id: str,
    new_version: int,
    new_s3_prefix: str,
    new_manifest: dict,
    new_manifest_sha256: str,
    approved_by: str,
) -> None:
    """Atomic flip: write new version + update LATEST on listings.

    Uses DynamoDB TransactWriteItems so either both writes succeed or neither
    does. Without this, a torn write could leave LATEST pointing at v2 while
    the versions row is missing.
    """
    client = _dynamodb_client()
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    listings_tbl = settings.MARKETPLACE_LISTINGS_TABLE
    versions_tbl = settings.MARKETPLACE_LISTING_VERSIONS_TABLE
    client.transact_write_items(
        TransactItems=[
            {
                "Put": {
                    "TableName": versions_tbl,
                    "Item": {
                        "listing_id": {"S": listing_id},
                        "version": {"N": str(new_version)},
                        "s3_prefix": {"S": new_s3_prefix},
                        "manifest_sha256": {"S": new_manifest_sha256},
                        "published_at": {"S": now_iso},
                        "published_by": {"S": approved_by},
                    },
                },
            },
            {
                "Update": {
                    "TableName": listings_tbl,
                    "Key": {
                        "listing_id": {"S": listing_id},
                        "version": {"N": str(new_version)},
                    },
                    # Fail loud if the v2 listings row hasn't been seeded yet
                    # (e.g., via create_draft for the new version). Without
                    # this guard, DynamoDB Update is upsert-by-default and
                    # would silently create a v2 row populated only with the
                    # 4 fields below — half-populated rows surface as broken
                    # listings in the storefront. Caller MUST insert the full
                    # v2 row in 'review' state before calling publish_v2.
                    "ConditionExpression": "attribute_exists(listing_id)",
                    "UpdateExpression": (
                        "SET #s = :pub,     published_at = :now,     s3_prefix = :prefix,     manifest_sha256 = :sha"
                    ),
                    "ExpressionAttributeNames": {"#s": "status"},
                    "ExpressionAttributeValues": {
                        ":pub": {"S": "published"},
                        ":now": {"S": now_iso},
                        ":prefix": {"S": new_s3_prefix},
                        ":sha": {"S": new_manifest_sha256},
                    },
                },
            },
        ]
    )


async def get_by_slug(*, slug: str) -> dict | None:
    """Look up listing by slug. Returns the highest-version row."""
    table = _listings_table()
    resp = table.query(
        IndexName="slug-version-index",
        KeyConditionExpression="slug = :s",
        ExpressionAttributeValues={":s": slug},
        ScanIndexForward=False,  # newest version first
        Limit=1,
    )
    items = resp.get("Items", [])
    return items[0] if items else None


async def get_by_id(*, listing_id: str, version: int) -> dict | None:
    """Look up listing by id + version."""
    table = _listings_table()
    resp = table.get_item(Key={"listing_id": listing_id, "version": version})
    return resp.get("Item")
