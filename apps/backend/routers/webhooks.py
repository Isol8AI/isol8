"""Clerk webhook router.

Receives lifecycle events from Clerk (user.created, user.updated, user.deleted)
and keeps internal state in sync.

Verification uses the svix HMAC-SHA256 signature scheme:
  https://docs.svix.com/receiving/verifying-payloads/how

If CLERK_WEBHOOK_SECRET is not configured the signature check is skipped
(safe for local dev; must be set in production).
"""

import base64
import hashlib
import hmac
import json
import logging
import time

from botocore.exceptions import ClientError
from fastapi import APIRouter, HTTPException, Request

from core.config import settings
from core.dynamodb import get_table, run_in_thread
from core.observability.metrics import put_metric
from core.repositories import channel_link_repo

logger = logging.getLogger(__name__)

router = APIRouter()


def _verify_svix_signature(body: bytes, headers: dict) -> None:
    """Raise HTTPException(400) if the svix signature is invalid.

    Svix signs the payload with HMAC-SHA256 using a timestamp + body
    combination.  The ``svix-signature`` header contains one or more
    ``v1,<base64>`` tokens; we accept the payload if ANY token matches.

    Skipped when CLERK_WEBHOOK_SECRET is not configured (local dev).
    """
    secret = settings.CLERK_WEBHOOK_SECRET
    if not secret:
        return

    # Strip the ``whsec_`` prefix that Clerk/svix adds to the secret.
    raw_secret = secret.removeprefix("whsec_")
    try:
        key = base64.b64decode(raw_secret)
    except Exception:
        logger.warning("CLERK_WEBHOOK_SECRET is not valid base64; skipping signature check")
        return

    msg_id = headers.get("svix-id", "")
    msg_timestamp = headers.get("svix-timestamp", "")
    msg_signature = headers.get("svix-signature", "")

    if not msg_id or not msg_timestamp or not msg_signature:
        put_metric("webhook.clerk.sig_fail")
        raise HTTPException(status_code=400, detail="Missing svix signature headers")

    signed_content = f"{msg_id}.{msg_timestamp}.".encode() + body
    expected = hmac.new(key, signed_content, hashlib.sha256).digest()
    expected_b64 = base64.b64encode(expected).decode()

    # svix-signature may contain multiple space-separated tokens.
    tokens = msg_signature.split(" ")
    for token in tokens:
        if token.startswith("v1,"):
            candidate = token[3:]
            if hmac.compare_digest(expected_b64, candidate):
                return

    put_metric("webhook.clerk.sig_fail")
    raise HTTPException(status_code=400, detail="Invalid svix signature")


async def _check_clerk_webhook_dedup(event_id: str) -> bool:
    """Returns True if this Clerk webhook event was already processed."""
    table = get_table("webhook-event-dedup")

    def _put():
        table.put_item(
            Item={
                "event_id": f"clerk:{event_id}",
                "ttl": int(time.time()) + 30 * 86400,
            },
            ConditionExpression="attribute_not_exists(event_id)",
        )

    try:
        await run_in_thread(_put)
        return False
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return True
        raise


@router.post(
    "/clerk",
    summary="Handle Clerk webhooks",
    description="Processes Clerk lifecycle events (user.created, user.updated, user.deleted).",
    operation_id="handle_clerk_webhook",
    include_in_schema=False,
)
async def handle_clerk_webhook(request: Request):
    """Handle Clerk webhook events. No Clerk JWT auth — uses svix signature."""
    body = await request.body()
    _verify_svix_signature(body, dict(request.headers))

    try:
        payload = json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Idempotency check — svix-id is the unique event identifier
    svix_id = request.headers.get("svix-id", "")
    if svix_id:
        try:
            if await _check_clerk_webhook_dedup(svix_id):
                put_metric("webhook.clerk.duplicate")
                logger.info("Duplicate Clerk webhook event %s, skipping", svix_id)
                return {"status": "ok"}
        except Exception:
            logger.warning("Clerk webhook dedup check failed for %s, processing anyway", svix_id)

    event_type = payload.get("type", "")
    data = payload.get("data", {})
    put_metric("webhook.clerk.received", dimensions={"event_type": event_type})

    if event_type == "user.created":
        user_id = data.get("id", "")
        logger.info("Clerk user.created webhook received for %s", user_id)

    elif event_type == "user.updated":
        user_id = data.get("id", "")
        logger.info("Clerk user.updated webhook received for %s", user_id)

    elif event_type == "user.deleted":
        user_id = data.get("id", "")
        if not user_id:
            logger.warning("Clerk user.deleted webhook missing data.id")
            return {"status": "ok"}

        count = await channel_link_repo.sweep_by_member(user_id)
        logger.info(
            "Clerk user.deleted webhook: swept %d channel_link rows for %s",
            count,
            user_id,
        )

    else:
        logger.debug("Clerk webhook: unhandled event type %s", event_type)

    return {"status": "ok"}
