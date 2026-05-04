"""Marketplace listings service.

Wraps catalog_service for packaging; adds:
  - listing-level metadata (price, seller, status)
  - state machine (draft -> review -> published -> retired/taken_down)
  - v2 publish via DynamoDB TransactWriteItems for atomicity (atomically
    flips v_new -> 'published' and v_prev -> 'retired' so only one row
    per listing_id is ever 'published')

Single-table design: every version is a row in `listings` keyed by
(listing_id, version). The version-history requirement is satisfied by
the rows themselves — older versions stay in the table with status
'retired'. No separate immutable history table.
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


def _dynamodb_client():
    return boto3.client("dynamodb")


class InvalidStateError(Exception):
    """Listing is not in the state required for the operation."""


class SlugCollisionError(Exception):
    """Another listing already owns this slug."""


class ArtifactNotUploadedError(Exception):
    """Seller called submit_for_review on a draft whose artifact bytes
    were never replaced. create_draft writes a metadata-only artifact
    (artifact_uploaded=False); the seller must call replace_artifact
    via /artifact-from-agent before submit_for_review will accept the
    draft.
    """


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
        "price_cents": price_cents,
        "tags": tags,
        "seller_id": seller_id,
        "status": "draft",
        "s3_prefix": s3_prefix,
        "manifest_sha256": sha,
        "manifest_json": manifest,
        "artifact_format_version": "v1",
        "entitlement_policy": "perpetual",
        # False until replace_artifact writes the real bytes.
        # submit_for_review requires this to be True.
        "artifact_uploaded": False,
        "created_at": now_iso,
        "updated_at": now_iso,
        "published_at": None,
    }
    table.put_item(Item=item)
    return item


async def replace_artifact(
    *,
    listing_id: str,
    seller_id: str,
    artifact_bytes: bytes,
    manifest: dict,
) -> dict:
    """Replace the v1 artifact for a draft listing.

    Conditional on (seller_id matches the listing's seller) AND
    (status='draft'). Re-uploads to the same S3 prefix so the existing
    version is overwritten — artifacts are mutable until the listing
    first transitions out of draft.

    Returns:
        Dict with the updated listing fields: listing_id, version,
        manifest_sha256, file_count, bytes.

    Raises:
        InvalidStateError: Listing is not in draft state, or caller is
        not the seller.
    """
    table = _listings_table()
    # Read first to verify ownership + state. We can't use a conditional
    # update for the upload because the S3 write happens before the DDB
    # update; verifying ownership upfront keeps the failure mode tight.
    resp = table.get_item(Key={"listing_id": listing_id, "version": 1})
    item = resp.get("Item")
    if not item:
        raise InvalidStateError("listing not found")
    if item.get("seller_id") != seller_id:
        raise InvalidStateError("you are not the seller of this listing")
    if item.get("status") != "draft":
        raise InvalidStateError("artifact can only be replaced while in 'draft' state")

    s3_prefix, sha = await _upload_artifact_to_s3(
        listing_id=listing_id,
        version=1,
        artifact_bytes=artifact_bytes,
        manifest=manifest,
    )
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    table.update_item(
        Key={"listing_id": listing_id, "version": 1},
        UpdateExpression=(
            "SET manifest_sha256 = :sha, manifest_json = :mj,"
            "    s3_prefix = :prefix, artifact_uploaded = :uploaded,"
            "    updated_at = :now"
        ),
        # Defense-in-depth: re-check seller match + draft state via condition
        # in case state changed between the get and update.
        ConditionExpression="seller_id = :sid AND #s = :draft",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":sha": sha,
            ":mj": manifest,
            ":prefix": s3_prefix,
            ":uploaded": True,
            ":sid": seller_id,
            ":draft": "draft",
            ":now": now_iso,
        },
    )

    return {
        "listing_id": listing_id,
        "version": 1,
        "manifest_sha256": sha,
        "file_count": len(manifest.get("contents", [])) or manifest.get("file_count", 0),
        "bytes": len(artifact_bytes),
    }


async def submit_for_review(*, listing_id: str, seller_id: str) -> dict:
    """Transition draft -> review. Idempotent: re-submitting from review is rejected.

    Precondition: artifact_uploaded must be True. Listings created via
    create_draft start with artifact_uploaded=False; the seller must
    call replace_artifact via /artifact-from-agent before submit_for_review
    will accept the draft. Without this guard, sellers could submit a
    metadata-only draft with an empty workspace.tar.gz and buyers would
    get an empty install.
    """
    table = _listings_table()

    # Pre-check artifact_uploaded so we can return a specific error.
    # Listings created before this field existed default to True (legacy
    # safety) — the field is only stored for newly-created drafts.
    pre = table.get_item(Key={"listing_id": listing_id, "version": 1})
    pre_item = pre.get("Item") or {}
    if pre_item.get("artifact_uploaded") is False:
        raise ArtifactNotUploadedError("upload artifact before submitting for review")

    try:
        # Populate published_at at submit time even though the listing isn't
        # yet "published". status-published-index has published_at as its
        # sort key; DynamoDB's sparse-GSI semantics exclude items whose sort
        # key is missing. Without a value here the moderation queue
        # (status="review") is structurally empty regardless of how many
        # listings are awaiting review. The approve flow overwrites this on
        # the actual publish transition, so the field still tells you when
        # the listing went live (or when it last entered the review pipeline,
        # if rejected).
        resp = table.update_item(
            Key={"listing_id": listing_id, "version": 1},
            UpdateExpression="SET #s = :review, updated_at = :now, published_at = :now",
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
    """Admin transition: review -> published. Sets published_at + published_by.

    Used for the FIRST publish of a listing (v=1). For subsequent versions
    that need to atomically retire the previous published version, callers
    use publish_v2 instead.
    """
    table = _listings_table()
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        resp = table.update_item(
            Key={"listing_id": listing_id, "version": version},
            UpdateExpression=("SET #s = :pub, published_at = :now, published_by = :by, updated_at = :now"),
            ConditionExpression="#s = :review",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":review": "review",
                ":pub": "published",
                ":now": now_iso,
                ":by": approved_by,
            },
            ReturnValues="ALL_NEW",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise InvalidStateError(f"listing v{version} is not in 'review' state")
        raise
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
    prev_version: int,
    new_version: int,
    approved_by: str,
) -> None:
    """Atomic flip: prev_version -> 'retired', new_version -> 'published'.

    Both rows live in the listings table (single-table design). The
    TransactWriteItems guarantees no observable state where two versions
    of the same listing_id are simultaneously 'published'.

    Preconditions (caller responsibility):
    - The new_version row exists in the listings table with status='review'
      (write it via create_draft-style insert before calling).
    - The prev_version row currently has status='published'.

    Conditional checks fail loudly if either precondition is violated.
    """
    client = _dynamodb_client()
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    listings_tbl = settings.MARKETPLACE_LISTINGS_TABLE
    client.transact_write_items(
        TransactItems=[
            {
                "Update": {
                    "TableName": listings_tbl,
                    "Key": {
                        "listing_id": {"S": listing_id},
                        "version": {"N": str(prev_version)},
                    },
                    "ConditionExpression": "#s = :pub",
                    "UpdateExpression": "SET #s = :retired, updated_at = :now",
                    "ExpressionAttributeNames": {"#s": "status"},
                    "ExpressionAttributeValues": {
                        ":pub": {"S": "published"},
                        ":retired": {"S": "retired"},
                        ":now": {"S": now_iso},
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
                    "ConditionExpression": "#s = :review",
                    "UpdateExpression": ("SET #s = :pub, published_at = :now, published_by = :by, updated_at = :now"),
                    "ExpressionAttributeNames": {"#s": "status"},
                    "ExpressionAttributeValues": {
                        ":review": {"S": "review"},
                        ":pub": {"S": "published"},
                        ":now": {"S": now_iso},
                        ":by": {"S": approved_by},
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
