"""Takedown / DMCA workflow.

Two flavors:
- file_takedown(): public form submission, creates a takedowns row in 'pending'.
- execute_full_takedown(): admin action; flips listing to taken_down, revokes
  all license keys, queues refunds for purchases in last 30 days.
"""

import time
import uuid
from typing import Literal

import boto3

from core.config import settings
from core.services import license_service


def _takedowns_table():
    return boto3.resource("dynamodb").Table(settings.MARKETPLACE_TAKEDOWNS_TABLE)


def _purchases_table():
    return boto3.resource("dynamodb").Table(settings.MARKETPLACE_PURCHASES_TABLE)


def _listings_table():
    return boto3.resource("dynamodb").Table(settings.MARKETPLACE_LISTINGS_TABLE)


async def file_takedown(
    *,
    listing_id: str,
    reason: Literal["dmca", "policy", "fraud", "seller-request"],
    claimant_name: str,
    claimant_email: str,
    basis_md: str,
) -> str:
    """Create a pending takedown row. Returns takedown_id."""
    tid = str(uuid.uuid4())
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _takedowns_table().put_item(
        Item={
            "listing_id": listing_id,
            "takedown_id": tid,
            "reason": reason,
            "filed_by_name": claimant_name,
            "filed_by_email": claimant_email,
            "basis_md": basis_md,
            "filed_at": now_iso,
            "decision": "pending",
        }
    )
    return tid


async def execute_full_takedown(*, listing_id: str, takedown_id: str, decided_by: str) -> None:
    """Admin action: flip listing to taken_down, revoke all licenses."""
    purchases = _purchases_table().query(
        IndexName="listing-created-index",
        KeyConditionExpression="listing_id = :l",
        ExpressionAttributeValues={":l": listing_id},
    )
    items = purchases.get("Items", [])
    for purchase in items:
        await license_service.revoke(
            purchase_id=purchase["purchase_id"],
            buyer_id=purchase["buyer_id"],
            reason="takedown",
        )

    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _listings_table().update_item(
        Key={"listing_id": listing_id, "version": 1},
        UpdateExpression="SET #s = :taken, updated_at = :now",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":taken": "taken_down", ":now": now_iso},
    )
    _takedowns_table().update_item(
        Key={"listing_id": listing_id, "takedown_id": takedown_id},
        UpdateExpression=("SET decision = :granted, decided_by = :by, decided_at = :now, affected_purchases = :n"),
        ExpressionAttributeValues={
            ":granted": "granted",
            ":by": decided_by,
            ":now": now_iso,
            ":n": len(items),
        },
    )
