"""Clerk webhook router.

Receives lifecycle events from Clerk (user, organization,
organizationMembership) and keeps internal state — including the
Paperclip mirror — in sync.

Verification uses the svix HMAC-SHA256 signature scheme:
  https://docs.svix.com/receiving/verifying-payloads/how

If CLERK_WEBHOOK_SECRET is not configured the signature check is skipped
(safe for local dev; must be set in production).

**Paperclip provisioning dispatch** (added in T12):

  * ``organization.created``           -> ``provision_org``
  * ``organizationMembership.created`` -> ``provision_member``
  * ``organizationMembership.deleted`` -> ``disable`` for that user
  * ``organization.deleted``           -> ``disable`` for every member of the org
  * ``user.deleted``                   -> ``disable`` for that user

Retry semantics: if provisioning raises an exception with
``retryable=True`` (``OrgNotProvisionedError`` always; ``PaperclipApiError``
on 5xx + 429), we enqueue a row in the ``pending-updates`` table for the
T13 cleanup cron to re-drive. Either way we return 200 to Clerk so the
svix delivery is acked — we own retries from this point onward.

Non-retryable errors (4xx state errors, programmer errors) are logged
and swallowed; returning 5xx would just have Clerk retry the same
permanently-broken event.
"""

import base64
import hashlib
import hmac
import json
import logging
import time
from typing import Any, Optional

import httpx
import stripe
from fastapi import APIRouter, HTTPException, Request

from core.config import settings
from core.observability.metrics import put_metric
from core.repositories import billing_repo, channel_link_repo, update_repo
from core.services.update_service import PAPERCLIP_RETRY_KIND as _PAPERCLIP_RETRY_KIND

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


# ----------------------------------------------------------------------
# Paperclip provisioning factory
# ----------------------------------------------------------------------
#
# We construct a fresh PaperclipProvisioning per webhook invocation. The
# httpx.AsyncClient lifecycle is bounded by the request — this is the
# only call site so the connection pool doesn't need to be shared, and
# constructing per-request keeps the wiring trivial to override in tests.
# T14/T15 (proxy router) will introduce a long-lived shared client.

# The canonical home for ``_PAPERCLIP_RETRY_KIND`` is
# ``core.services.update_service.PAPERCLIP_RETRY_KIND``. Both this
# webhook router (which enqueues retries) and the scheduled worker
# (which consumes them) read the same constant — keeping them in
# lockstep is the only way the retry cron actually picks up the
# rows we wrote. The import lives at the top of this file alongside
# the other ``core.*`` imports.


async def _get_paperclip_provisioning():
    """Build a PaperclipProvisioning for this request.

    Returns a ``PaperclipProvisioning`` instance. The underlying
    ``httpx.AsyncClient`` is attached as ``provisioning._http_client``
    so handlers can close it via ``aclose()`` after use — keeping the
    socket from leaking on production webhook traffic. T14/T15 will
    replace this per-request construction with a long-lived shared
    client tied to the FastAPI app lifespan.

    Imports are local to keep cold-start cheap (httpx + boto3 chain
    aren't needed if no Paperclip-bound webhook fires) and to keep the
    legacy webhook handlers working unchanged when Paperclip env is not
    configured (e.g. local dev without paperclip running).
    """
    from core.repositories.paperclip_repo import PaperclipRepo
    from core.services.paperclip_admin_client import PaperclipAdminClient
    from core.services.paperclip_provisioning import PaperclipProvisioning

    http = httpx.AsyncClient(
        base_url=settings.PAPERCLIP_INTERNAL_URL,
        timeout=15.0,
    )
    admin = PaperclipAdminClient(http_client=http)
    repo = PaperclipRepo(table_name=f"isol8-{settings.ENVIRONMENT}-paperclip-companies")
    provisioning = PaperclipProvisioning(admin, repo, env_name=settings.ENVIRONMENT)
    # Expose the underlying client for cleanup. Tests that patch
    # _get_paperclip_provisioning return AsyncMock-shaped objects that
    # don't carry this attribute, so consumers must guard with getattr.
    provisioning._http_client = http  # type: ignore[attr-defined]
    return provisioning


async def _close_paperclip_http(provisioning) -> None:
    """Close the underlying httpx client if one was attached.

    AsyncMock-shaped objects (used in tests) won't have the attribute,
    so we no-op gracefully — keeps the production cleanup hot path
    working without breaking the test patches.
    """
    http = getattr(provisioning, "_http_client", None)
    if http is None:
        return
    try:
        await http.aclose()
    except Exception:
        logger.exception("paperclip httpx client close failed")


async def _enqueue_paperclip_retry(*, op: str, payload: dict, owner_id: str) -> None:
    """Enqueue a Paperclip provisioning retry row in pending-updates.

    ``owner_id`` is the partition key of the pending-updates table —
    we use the affected user_id (or org owner) so T13 can group
    retries per-tenant. ``op`` distinguishes which provisioning entry
    point T13 should call back into.

    Failure to enqueue is logged but not re-raised: enqueueing is
    best-effort, and the alternative (5xx-ing the webhook) would just
    have Clerk retry the original event, which has the same retryable
    classification.
    """
    try:
        await update_repo.create(
            owner_id=owner_id,
            update_type=_PAPERCLIP_RETRY_KIND,
            description=f"Retry {op} (Paperclip)",
            changes={"op": op, **payload},
        )
        put_metric("paperclip.webhook.retry_enqueued", dimensions={"op": op})
    except Exception:
        logger.exception(
            "paperclip retry enqueue failed (op=%s, owner_id=%s)",
            op,
            owner_id,
        )


def _is_retryable(exc: BaseException) -> bool:
    """Read the ``retryable`` attribute from a Paperclip exception.

    ``OrgNotProvisionedError`` carries a class-level ``retryable=True``;
    ``PaperclipApiError`` sets ``retryable`` in __init__ from the
    status code (5xx + 429 => True). Anything else is treated as
    non-retryable.
    """
    return bool(getattr(exc, "retryable", False))


# ----------------------------------------------------------------------
# Clerk org event payload helpers
# ----------------------------------------------------------------------
#
# Clerk webhook payload shapes (verified against
# https://clerk.com/docs/webhooks/event-shapes):
#
# organization.created:
#   data.id                         -- org_id (e.g. "org_2abc...")
#   data.created_by                 -- user_id of the org owner
#   data.name, data.slug, data.created_at, ...
#
# organizationMembership.created / deleted:
#   data.id                         -- membership id
#   data.organization.id            -- org_id
#   data.organization.created_by    -- org owner's user_id
#   data.public_user_data.user_id   -- the affected member's user_id
#   data.public_user_data.identifier -- the member's primary email
#   data.role                       -- "org:admin" | "org:member" | ...
#
# organization.deleted:
#   data.id                         -- the deleted org_id
#   (deleted=true, slug present, members NOT enumerated — Clerk fires
#    organizationMembership.deleted separately for each member)
#
# user.deleted:
#   data.id                         -- the deleted user_id
#   data.deleted = True
def _extract_org_member_email(data: dict) -> Optional[str]:
    """Pull the new member's primary email out of an organizationMembership
    payload. Clerk packages the email under ``public_user_data.identifier``
    for both ``.created`` and ``.deleted`` events; older payload shapes used
    a sibling ``email_addresses`` array. We try both for forward/backward
    compatibility.
    """
    pud = data.get("public_user_data") or {}
    identifier = pud.get("identifier")
    if identifier:
        return identifier
    # Fallback for older / non-standard payload shapes.
    addrs = data.get("email_addresses") or pud.get("email_addresses") or []
    for a in addrs:
        if a.get("email_address"):
            return a["email_address"]
    return None


def _extract_primary_email(data: dict) -> Optional[str]:
    """Pull a Clerk user's primary email from a ``user.*`` payload.

    Clerk's ``user.created`` / ``user.updated`` payload shape:

        {
          "data": {
            "id": "user_xxx",
            "email_addresses": [
              {"id": "idn_xxx", "email_address": "u@example.com", ...},
              ...
            ],
            "primary_email_address_id": "idn_xxx",
            ...
          }
        }

    We resolve the entry whose ``id`` matches ``primary_email_address_id``;
    if that lookup fails (older payload shape, or Clerk omitted the
    pointer) we fall back to the first email in the array. Returns
    ``None`` if no usable email is present.
    """
    primary_id = data.get("primary_email_address_id")
    addresses = data.get("email_addresses") or []
    if primary_id:
        for entry in addresses:
            if isinstance(entry, dict) and entry.get("id") == primary_id:
                addr = entry.get("email_address")
                if addr:
                    return addr
    # Fallback: first email.
    for entry in addresses:
        if isinstance(entry, dict):
            addr = entry.get("email_address")
            if addr:
                return addr
    return None


async def _lookup_owner_email(*, org_id: str, fallback_user_id: Optional[str]) -> Optional[str]:
    """Pull the org owner's email so ``provision_member`` can sign them in.

    For ``organizationMembership.created`` Clerk's payload includes
    ``data.organization.created_by`` (the owner's user_id), but NOT the
    owner's email. We read it from the ``users`` repo where the
    ``user.created`` webhook persisted it. If the row is missing or
    lacks an email, return None — the caller's existing retry path
    will re-drive once the row is backfilled.
    """
    if not fallback_user_id:
        return None
    from core.repositories import user_repo

    try:
        row = await user_repo.get(fallback_user_id)
        if row and row.get("email"):
            return row["email"]
    except Exception:
        logger.exception("owner email lookup failed for org=%s", org_id)

    return None


# ----------------------------------------------------------------------
# Per-event handlers
# ----------------------------------------------------------------------


async def _handle_organization_created(data: dict) -> None:
    """Provision a Paperclip company for the newly-created Clerk org."""
    org_id = data.get("id", "")
    owner_user_id = data.get("created_by", "")
    if not org_id or not owner_user_id:
        logger.warning("Clerk organization.created missing id/created_by: %s", data)
        return

    # Owner email isn't on the organization payload — we fetch it from
    # the users repo (populated by user.created earlier in the lifecycle).
    owner_email = await _lookup_owner_email(org_id=org_id, fallback_user_id=owner_user_id)
    if not owner_email:
        logger.warning(
            "organization.created: no email for owner %s; enqueueing retry",
            owner_user_id,
        )
        await _enqueue_paperclip_retry(
            op="provision_org",
            payload={"org_id": org_id, "owner_user_id": owner_user_id, "owner_email": ""},
            owner_id=owner_user_id,
        )
        return

    provisioning = await _get_paperclip_provisioning()
    try:
        await provisioning.provision_org(
            org_id=org_id,
            owner_user_id=owner_user_id,
            owner_email=owner_email,
        )
        put_metric("paperclip.webhook.provision_org", dimensions={"result": "ok"})
    except Exception as e:
        retryable = _is_retryable(e)
        put_metric(
            "paperclip.webhook.provision_org",
            dimensions={"result": "retryable" if retryable else "error"},
        )
        logger.warning(
            "provision_org failed for org=%s owner=%s retryable=%s err=%s",
            org_id,
            owner_user_id,
            retryable,
            e,
        )
        if retryable:
            await _enqueue_paperclip_retry(
                op="provision_org",
                payload={
                    "org_id": org_id,
                    "owner_user_id": owner_user_id,
                    "owner_email": owner_email,
                },
                owner_id=owner_user_id,
            )
    finally:
        await _close_paperclip_http(provisioning)


async def _handle_organization_membership_created(data: dict) -> None:
    """Add the new member to the org's existing Paperclip company."""
    org = data.get("organization") or {}
    org_id = org.get("id", "")
    owner_user_id = org.get("created_by", "")
    pud = data.get("public_user_data") or {}
    user_id = pud.get("user_id", "") or data.get("user_id", "")
    email = _extract_org_member_email(data)

    if not org_id or not user_id or not email:
        logger.warning(
            "Clerk organizationMembership.created missing fields: org=%s user=%s email=%s",
            org_id,
            user_id,
            bool(email),
        )
        return

    owner_email = await _lookup_owner_email(org_id=org_id, fallback_user_id=owner_user_id)
    if not owner_email:
        logger.warning(
            "organizationMembership.created: no email for org %s owner %s; enqueueing retry",
            org_id,
            owner_user_id,
        )
        await _enqueue_paperclip_retry(
            op="provision_member",
            payload={
                "org_id": org_id,
                "user_id": user_id,
                "email": email,
                "owner_email": "",
            },
            owner_id=user_id,
        )
        return

    provisioning = await _get_paperclip_provisioning()
    try:
        await provisioning.provision_member(
            org_id=org_id,
            user_id=user_id,
            email=email,
            owner_email=owner_email,
        )
        put_metric("paperclip.webhook.provision_member", dimensions={"result": "ok"})
    except Exception as e:
        retryable = _is_retryable(e)
        put_metric(
            "paperclip.webhook.provision_member",
            dimensions={"result": "retryable" if retryable else "error"},
        )
        logger.warning(
            "provision_member failed for org=%s user=%s retryable=%s err=%s",
            org_id,
            user_id,
            retryable,
            e,
        )
        if retryable:
            await _enqueue_paperclip_retry(
                op="provision_member",
                payload={
                    "org_id": org_id,
                    "user_id": user_id,
                    "email": email,
                    "owner_email": owner_email,
                },
                owner_id=user_id,
            )
    finally:
        await _close_paperclip_http(provisioning)


async def _handle_organization_membership_deleted(data: dict) -> None:
    """Disable Paperclip for a single removed member."""
    pud = data.get("public_user_data") or {}
    user_id = pud.get("user_id", "") or data.get("user_id", "")
    if not user_id:
        logger.warning("Clerk organizationMembership.deleted missing user_id: %s", data)
        return

    provisioning = await _get_paperclip_provisioning()
    try:
        await provisioning.disable(user_id=user_id)
        put_metric("paperclip.webhook.disable", dimensions={"trigger": "membership_deleted"})
    except Exception:
        # disable() doesn't raise PaperclipApiError today (DDB-only), but
        # belt-and-braces: log and continue. We don't enqueue a retry —
        # disable is purely local and a transient DDB hiccup is rare.
        logger.exception("disable on membership_deleted failed for user=%s", user_id)
    finally:
        await _close_paperclip_http(provisioning)


async def _handle_organization_deleted(data: dict) -> None:
    """Disable every Paperclip member row attached to the deleted org.

    Clerk also fires ``organizationMembership.deleted`` for each
    member, but we belt-and-braces against missed events by sweeping
    the org-id GSI. ``disable`` is idempotent so a double-fire is safe.
    """
    org_id = data.get("id", "")
    if not org_id:
        logger.warning("Clerk organization.deleted missing id: %s", data)
        return

    from boto3.dynamodb.conditions import Key

    from core.dynamodb import run_in_thread

    provisioning = await _get_paperclip_provisioning()
    try:
        # Reach through the repo to the underlying GSI to enumerate members.
        # We could promote this into the repo, but for v1 the only caller
        # is this webhook handler and adding a public method now would
        # outgrow its single use site.
        table = provisioning._repo._table()  # noqa: SLF001 — same package, single call site
        last_key = None
        disabled = 0
        while True:
            kwargs: dict = {
                "IndexName": "by-org-id",
                "KeyConditionExpression": Key("org_id").eq(org_id),
            }
            if last_key is not None:
                kwargs["ExclusiveStartKey"] = last_key
            resp = await run_in_thread(table.query, **kwargs)
            for item in resp.get("Items", []):
                uid = item.get("user_id")
                if not uid:
                    continue
                try:
                    await provisioning.disable(user_id=uid)
                    disabled += 1
                except Exception:
                    logger.exception(
                        "disable on organization.deleted failed for user=%s org=%s",
                        uid,
                        org_id,
                    )
            last_key = resp.get("LastEvaluatedKey")
            if not last_key:
                break
        put_metric(
            "paperclip.webhook.disable",
            value=disabled,
            dimensions={"trigger": "organization_deleted"},
        )
        logger.info(
            "Clerk organization.deleted: disabled %d member rows for org %s",
            disabled,
            org_id,
        )
    finally:
        await _close_paperclip_http(provisioning)


async def _handle_user_deleted_paperclip(user_id: str) -> None:
    """Disable Paperclip for a deleted Clerk user."""
    provisioning = await _get_paperclip_provisioning()
    try:
        await provisioning.disable(user_id=user_id)
        put_metric("paperclip.webhook.disable", dimensions={"trigger": "user_deleted"})
    except Exception:
        logger.exception("disable on user_deleted failed for user=%s", user_id)
    finally:
        await _close_paperclip_http(provisioning)


# ----------------------------------------------------------------------
# Routes
# ----------------------------------------------------------------------


@router.post(
    "/clerk",
    summary="Handle Clerk webhooks",
    description=(
        "Processes Clerk lifecycle events: user.created, user.updated, user.deleted, "
        "organization.created/deleted, organizationMembership.created/deleted."
    ),
    operation_id="handle_clerk_webhook",
    include_in_schema=False,
)
async def handle_clerk_webhook(request: Request):
    """Handle Clerk webhook events. No Clerk JWT auth — uses svix signature."""
    body = await request.body()
    _verify_svix_signature(body, dict(request.headers))

    # Idempotency dedupe — svix will retry on any non-2xx and on its own
    # at-least-once delivery insurance. Without this, two retries from
    # svix on a flaky webhook would each call ``provision_org``, the
    # second of which fails with email-collision (409 from Better Auth,
    # non-retryable) and marks the row failed forever. Keyed on svix-id
    # which is unique per genuine Clerk event, identical across retries.
    svix_id = request.headers.get("svix-id")
    if svix_id:
        try:
            from core.services.webhook_dedup import (
                WebhookDedupResult,
                record_event_or_skip,
            )

            dedup = await record_event_or_skip(svix_id, source="clerk")
            if dedup is WebhookDedupResult.ALREADY_SEEN:
                put_metric("clerk.webhook.dedup_skipped")
                logger.info("clerk webhook duplicate suppressed: %s", svix_id)
                return {"status": "duplicate"}
        except Exception:
            # Dedupe is best-effort — a misconfigured WEBHOOK_DEDUP_TABLE
            # shouldn't black-hole all Clerk webhooks. Log and continue
            # so genuine traffic still flows; the worst case (DDB
            # outage) reverts to the pre-dedupe behavior of double-handling
            # a retry, which the per-event idempotency in provision_*
            # already mostly tolerates.
            logger.exception("clerk webhook dedupe check failed; processing anyway")

    try:
        payload = json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event_type = payload.get("type", "")
    data: dict[str, Any] = payload.get("data", {})
    put_metric("webhook.clerk.received", dimensions={"event_type": event_type})

    if event_type == "user.created":
        user_id = data.get("id", "")
        logger.info("Clerk user.created webhook received for %s", user_id)

        # Persist user_id + primary email into the users table. The email
        # column is what ``_lookup_owner_email`` (and the Paperclip
        # provisioning chain) reads to sign the org owner in to Better
        # Auth — without this, organization.created webhooks never find
        # an email and would loop on retries forever. The /users/sync
        # path also calls user_repo.put but only knows the user_id;
        # the webhook is the authoritative source of email.
        if user_id:
            email = _extract_primary_email(data)
            try:
                from core.repositories import user_repo

                await user_repo.put(user_id, email=email)
            except Exception:
                # Persistence is non-fatal here — the /users/sync REST
                # path will write the row again the first time the user
                # opens the app, and downstream paperclip handlers fall
                # back to Clerk admin API. Logging is enough.
                logger.exception("user_repo.put failed for user.created %s", user_id)

    elif event_type == "user.updated":
        user_id = data.get("id", "")
        logger.info("Clerk user.updated webhook received for %s", user_id)

        # Sync the primary email to the user's Stripe Customer if one exists.
        # Catches receipt / invoice / trial-end emails going to a stale address.
        new_email = _extract_primary_email(data)
        if new_email and user_id:
            account = await billing_repo.get_by_owner_id(user_id)
            if account and account.get("stripe_customer_id"):
                # Use the Clerk webhook's unique svix-id as the Stripe idempotency
                # key. Each genuine Clerk event gets a unique id; a retry of the
                # SAME event reuses it. Embedding user_id+email instead would let
                # an A→B→A→B email flip within Stripe's 24h idempotency window
                # collide with the first A→B and silently skip the modify.
                svix_id = request.headers.get("svix-id")
                if svix_id:
                    idempotency_key = f"customer_email_sync:{svix_id}"
                else:
                    # Defensive fallback (shouldn't happen with real Clerk
                    # traffic — _verify_svix_signature already requires it
                    # when CLERK_WEBHOOK_SECRET is set). 1-min bucket bounds
                    # the worst-case skipped writes.
                    idempotency_key = f"customer_email_sync:{user_id}:{new_email}:{int(time.time() // 60)}"
                try:
                    stripe.Customer.modify(
                        account["stripe_customer_id"],
                        email=new_email,
                        idempotency_key=idempotency_key,
                    )
                    put_metric("stripe.customer.email_sync", dimensions={"result": "ok"})
                except stripe.StripeError as e:
                    put_metric("stripe.customer.email_sync", dimensions={"result": "error"})
                    logger.warning(
                        "Stripe email sync failed for %s: %s",
                        user_id,
                        e,
                    )
                    # Non-fatal — Clerk update succeeded.

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
        # Disable Paperclip for this user (account-level deletion). Org
        # membership cleanup is handled via the organizationMembership
        # event stream — we don't enumerate orgs here.
        await _handle_user_deleted_paperclip(user_id)

    elif event_type == "organization.created":
        await _handle_organization_created(data)

    elif event_type == "organizationMembership.created":
        await _handle_organization_membership_created(data)

    elif event_type == "organizationMembership.deleted":
        await _handle_organization_membership_deleted(data)

    elif event_type == "organization.deleted":
        await _handle_organization_deleted(data)

    else:
        logger.debug("Clerk webhook: unhandled event type %s", event_type)

    return {"status": "ok"}
