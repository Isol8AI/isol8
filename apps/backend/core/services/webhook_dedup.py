"""Idempotency helper for inbound webhooks (Stripe primarily, Clerk also).

Reuses the existing `isol8-{env}-webhook-event-dedup` DynamoDB table provisioned
by the database stack. Items have a 30-day TTL so the table never grows
unboundedly.

Pattern (per spec §8.4):
    result = await record_event_or_skip(event.id, source="stripe")
    if result is WebhookDedupResult.ALREADY_SEEN:
        return Response(status_code=200)  # silently ack the replay
    # ... process the event ...

Why a separate module: the dedup primitive is dead-simple (one conditional
PutItem) and used by >=2 callers. Keeping it out of the routers means the
idempotency contract is testable in isolation.
"""

from __future__ import annotations

import enum
import os
import time

import boto3
from botocore.exceptions import ClientError

from core.config import settings


_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days


class WebhookDedupResult(str, enum.Enum):
    RECORDED = "recorded"
    ALREADY_SEEN = "already_seen"


def _table():
    """Returns the boto3 Table resource. Created lazily so tests can monkeypatch
    the env var before the first call.

    Fails fast if WEBHOOK_DEDUP_TABLE is empty -- better a clear startup error
    than a confusing boto3 ValidationException on first webhook.

    Reads from os.environ rather than settings so tests can monkeypatch the
    env var after the settings singleton is constructed at import time.
    """
    table_name = os.environ.get("WEBHOOK_DEDUP_TABLE") or settings.WEBHOOK_DEDUP_TABLE
    if not table_name:
        raise RuntimeError(
            "WEBHOOK_DEDUP_TABLE is empty -- backend is misconfigured. "
            "Set the env var via service-stack.ts (already wired)."
        )
    return boto3.resource("dynamodb", region_name=settings.AWS_REGION).Table(table_name)


async def record_event_or_skip(event_id: str, *, source: str) -> WebhookDedupResult:
    """Conditionally record a webhook event_id.

    Returns RECORDED on the first call for a given event_id. Returns
    ALREADY_SEEN on every subsequent call. Backed by DynamoDB conditional
    PutItem (`attribute_not_exists(event_id)`).

    Args:
        event_id: provider-issued event id (Stripe `evt_*`, Clerk uuid).
        source: free-form tag stored alongside the row for debugging.
            Does NOT affect dedup keying -- event_id is the sole key.
    """
    now = int(time.time())
    try:
        _table().put_item(
            Item={
                "event_id": event_id,
                "source": source,
                "recorded_at": now,
                "ttl": now + _TTL_SECONDS,
            },
            ConditionExpression="attribute_not_exists(event_id)",
        )
        return WebhookDedupResult.RECORDED
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return WebhookDedupResult.ALREADY_SEEN
        raise
