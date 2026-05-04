"""Purchases, Stripe webhook, refunds.

Isol8-internal scope: buyers are signed-in Isol8 users who deploy
listings into their existing OpenClaw container via the deploy endpoint
in marketplace_listings. There is no CLI installer.
"""

import time
import uuid
from typing import Annotated

import boto3
import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request

from core.auth import AuthContext, get_current_user
from core.config import settings
from core.services import license_service, payout_service
from core.services import webhook_dedup
from core.services.webhook_dedup import WebhookDedupResult
from schemas import marketplace as schemas


router = APIRouter(prefix="/api/v1/marketplace", tags=["marketplace-purchases"])


def _purchases_table():
    return boto3.resource("dynamodb").Table(settings.MARKETPLACE_PURCHASES_TABLE)


def _payout_accounts_table():
    return boto3.resource("dynamodb").Table(settings.MARKETPLACE_PAYOUT_ACCOUNTS_TABLE)


@router.post("/checkout")
async def checkout(
    payload: schemas.CheckoutRequest,
    auth: Annotated[AuthContext, Depends(get_current_user)],
):
    """Create a Stripe Checkout session against the platform account."""
    from core.services import marketplace_service

    listing = await marketplace_service.get_by_slug(slug=payload.listing_slug)
    if not listing or listing["status"] != "published":
        raise HTTPException(status_code=404, detail="listing not available")
    if listing["price_cents"] == 0:
        raise HTTPException(status_code=400, detail="listing is free")

    stripe.api_key = settings.STRIPE_SECRET_KEY
    session = stripe.checkout.Session.create(
        mode="payment",
        success_url=payload.success_url,
        cancel_url=payload.cancel_url,
        customer_email=payload.email or None,
        line_items=[
            {
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": listing["name"]},
                    "unit_amount": listing["price_cents"],
                },
                "quantity": 1,
            }
        ],
        metadata={
            "listing_id": listing["listing_id"],
            "listing_slug": listing["slug"],
            "version": str(listing["version"]),
            "buyer_id": auth.user_id,
            "seller_id": listing["seller_id"],
        },
        payment_intent_data={
            "transfer_group": f"purchase_{listing['listing_id']}_{auth.user_id}_{int(time.time())}",
        },
        idempotency_key=f"checkout:{auth.user_id}:{listing['listing_id']}:{int(time.time() // 60)}",
    )
    return {"checkout_url": session.url, "session_id": session.id}


@router.post(
    "/webhooks/stripe-marketplace",
    summary="Stripe Connect webhook receiver for marketplace events",
    description=(
        "Receives Stripe Connect webhook events for the marketplace. Verifies "
        "the signature against STRIPE_CONNECT_WEBHOOK_SECRET (set in the task "
        "definition). Handles checkout.session.completed (records purchase + "
        "license + held balance), charge.refunded (revokes license), and "
        "account.updated (flushes held balance to seller's Connect account). "
        "Other event types are acknowledged 200 but not acted on. Idempotent "
        "via webhook_dedup."
    ),
)
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(..., alias="stripe-signature"),
):
    """Stripe Connect webhook receiver for marketplace events."""
    body = await request.body()
    try:
        event = stripe.Webhook.construct_event(body, stripe_signature, settings.STRIPE_CONNECT_WEBHOOK_SECRET)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"invalid signature: {e}")

    dedup = await webhook_dedup.record_event_or_skip(event_id=event["id"], source="stripe-marketplace")
    if dedup == WebhookDedupResult.ALREADY_SEEN:
        return {"status": "replay-acked"}

    event_type = event["type"]
    obj = event["data"]["object"]
    if event_type == "checkout.session.completed":
        await _handle_checkout_completed(obj)
    elif event_type == "charge.refunded":
        await _handle_charge_refunded(obj)
    elif event_type == "account.updated":
        await _handle_account_updated(obj)
    # Other events (transfer.failed, payout.paid, payout.failed) are
    # logged via Stripe; no immediate action in v1.
    return {"status": "ok"}


async def _handle_checkout_completed(session: dict) -> None:
    """Grant license + record purchase + bump seller's held balance.

    Captures the PaymentIntent's transfer_group on the purchase row so that
    /refund can pass the EXACT same key into payout_service.refund_purchase
    when looking up the seller transfer for reversal. Reconstructing the
    key client-side would miss because checkout includes a timestamp suffix.
    """
    metadata = session.get("metadata", {})
    listing_id = metadata.get("listing_id")
    buyer_id = metadata.get("buyer_id")
    seller_id = metadata.get("seller_id")
    version = int(metadata.get("version", "1"))
    amount = session.get("amount_total", 0)
    if not (listing_id and buyer_id and seller_id):
        return  # invalid session metadata, ignore.

    payment_intent_id = session.get("payment_intent")
    transfer_group = ""
    if payment_intent_id:
        try:
            stripe.api_key = settings.STRIPE_SECRET_KEY
            pi = stripe.PaymentIntent.retrieve(payment_intent_id)
            transfer_group = pi.get("transfer_group") or ""
        except stripe.error.StripeError:
            # Best-effort. Without transfer_group the refund flow can still
            # refund the buyer; only the Transfer Reversal lookup would miss.
            # Logged via Stripe's own audit; we continue.
            transfer_group = ""

    license_key = license_service.generate()
    purchase_id = str(uuid.uuid4())
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _purchases_table().put_item(
        Item={
            "buyer_id": buyer_id,
            "purchase_id": purchase_id,
            "listing_id": listing_id,
            "listing_version_at_purchase": version,
            "entitlement_version_floor": version,
            "price_paid_cents": amount,
            "stripe_payment_intent_id": payment_intent_id,
            "stripe_checkout_session_id": session.get("id"),
            "stripe_transfer_group": transfer_group,
            "license_key": license_key,
            "license_key_revoked": False,
            "status": "paid",
            "install_count": 0,
            "created_at": now_iso,
        }
    )
    _payout_accounts_table().update_item(
        Key={"seller_id": seller_id},
        UpdateExpression=(
            "SET balance_held_cents = if_not_exists(balance_held_cents, :zero) + :amt, "
            "    last_balance_update_at = :now"
        ),
        ExpressionAttributeValues={":zero": 0, ":amt": amount, ":now": now_iso},
    )


async def _handle_charge_refunded(charge: dict) -> None:
    """Revoke license on refund. Looks up the purchase via the
    payment-intent GSI — single Query, not a full-table scan.
    """
    payment_intent_id = charge.get("payment_intent")
    if not payment_intent_id:
        return
    table = _purchases_table()
    resp = table.query(
        IndexName="payment-intent-index",
        KeyConditionExpression="stripe_payment_intent_id = :pi",
        ExpressionAttributeValues={":pi": payment_intent_id},
        Limit=1,
    )
    items = resp.get("Items", [])
    if not items:
        return
    purchase = items[0]
    await license_service.revoke(
        purchase_id=purchase["purchase_id"],
        buyer_id=purchase["buyer_id"],
        reason="refunded",
    )


async def _handle_account_updated(account: dict) -> None:
    """If onboarding completed, flush held balance via Transfer."""
    if not account.get("payouts_enabled"):
        return
    seller_id = (account.get("metadata") or {}).get("seller_id")
    if not seller_id:
        return
    pa_table = _payout_accounts_table()
    resp = pa_table.get_item(Key={"seller_id": seller_id})
    pa = resp.get("Item", {})
    held = pa.get("balance_held_cents", 0)
    connect_account_id = pa.get("stripe_connect_account_id") or account.get("id")
    if held > 0 and connect_account_id:
        await payout_service.transfer_held_balance(
            connect_account_id=connect_account_id,
            amount_cents=held,
            transfer_group=f"flush_{seller_id}_{int(time.time())}",
        )
        pa_table.update_item(
            Key={"seller_id": seller_id},
            UpdateExpression=(
                "SET balance_held_cents = :zero, "
                "    onboarding_status = :done, "
                "    lifetime_earned_cents = if_not_exists(lifetime_earned_cents, :zero) + :h"
            ),
            ExpressionAttributeValues={
                ":zero": 0,
                ":done": "completed",
                ":h": held,
            },
        )


@router.post("/refund")
async def refund(
    purchase_id: str,
    auth: Annotated[AuthContext, Depends(get_current_user)],
):
    """7-day refund window for buyers."""
    table = _purchases_table()
    resp = table.get_item(Key={"buyer_id": auth.user_id, "purchase_id": purchase_id})
    purchase = resp.get("Item")
    if not purchase:
        raise HTTPException(status_code=404, detail="purchase not found")
    created_iso = purchase["created_at"]
    age_seconds = time.time() - time.mktime(time.strptime(created_iso, "%Y-%m-%dT%H:%M:%SZ"))
    if age_seconds > 7 * 24 * 60 * 60:
        raise HTTPException(status_code=403, detail="refund window expired (7 days)")

    result = await payout_service.refund_purchase(
        payment_intent_id=purchase["stripe_payment_intent_id"],
        transfer_group=purchase.get("stripe_transfer_group", ""),
        full_amount_cents=purchase["price_paid_cents"],
    )
    await license_service.revoke(purchase_id=purchase_id, buyer_id=auth.user_id, reason="refunded")
    return {"refund_id": result.refund_id, "reversal_id": result.reversal_id}


# ---------------------------------------------------------------------------
# Buyer purchase history surfacing
# ---------------------------------------------------------------------------


@router.get("/my-purchases", response_model=schemas.MyPurchasesResponse)
async def my_purchases(auth: Annotated[AuthContext, Depends(get_current_user)]):
    """List the caller's marketplace purchases.

    Queries marketplace-purchases by buyer_id (the table's PK). Joins the
    listing slug per row by reading marketplace-listings v1; small N
    (buyers don't buy thousands of items) makes the per-row read fine for v0.
    """
    table = _purchases_table()
    resp = table.query(
        KeyConditionExpression="buyer_id = :b",
        ExpressionAttributeValues={":b": auth.user_id},
        Limit=100,
        ScanIndexForward=False,  # newest first
    )

    items: list[schemas.PurchaseSummary] = []
    listings_table = boto3.resource("dynamodb").Table(settings.MARKETPLACE_LISTINGS_TABLE)
    slug_cache: dict[str, str] = {}
    for raw in resp.get("Items", []):
        listing_id = raw.get("listing_id", "")
        if listing_id and listing_id not in slug_cache:
            li = listings_table.get_item(Key={"listing_id": listing_id, "version": 1}).get("Item")
            slug_cache[listing_id] = (li or {}).get("slug", "") if li else ""
        items.append(
            schemas.PurchaseSummary(
                purchase_id=raw.get("purchase_id", ""),
                listing_id=listing_id,
                listing_slug=slug_cache.get(listing_id) or None,
                license_key=raw.get("license_key", ""),
                price_paid_cents=int(raw.get("price_paid_cents", 0)),
                status=raw.get("status", "paid"),
                created_at=raw.get("created_at", ""),
            )
        )
    return schemas.MyPurchasesResponse(items=items)
