"""Container lifecycle management endpoints.

Provides container status (with auto-retry for failed containers)
and a manual retry-provision endpoint.
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException

from core.auth import AuthContext, get_current_user, resolve_owner_id
from core.config import settings
from core.containers import get_ecs_manager, get_gateway_pool
from core.containers.ecs_manager import EcsManagerError
from core.services.management_api_client import ManagementApiClientError
from core.observability.metrics import put_metric, timing
from core.repositories import billing_repo, container_repo, user_repo

logger = logging.getLogger(__name__)

router = APIRouter()


def _resolve_cold_start_phase(container: dict, gateway_pool, owner_id: str) -> str:
    """Map (DDB container.status, gateway pool connection state) -> phase.

    Phases the frontend renders as a stepper. The gap between
    `provisioning` and `ready` is normally ~12 min today (5+ min wedge in
    upstream's sidecars.channels phase), so showing the user *something*
    during that window is the whole point of this surface.

    Returns:
      - "provisioning"  ECS task PROVISIONING / PENDING / STOPPED / error
      - "starting"      ECS task RUNNING but our pool hasn't completed
                        the OpenClaw handshake + health verification yet.
                        Covers gateway boot + sidecars.channels + qmd init.
      - "ready"         pool.is_user_connected() — openclaw is responsive
                        to RPCs, chat is usable.
    """
    status = (container or {}).get("status")
    if status != "running":
        return "provisioning"
    if gateway_pool.is_user_connected(owner_id):
        return "ready"
    return "starting"


async def _owner_has_subscription(owner_id: str) -> bool:
    """Check if an owner has an active billing subscription."""
    account = await billing_repo.get_by_owner_id(owner_id)
    return account is not None and account.get("stripe_subscription_id") is not None


# Subscription statuses that count as "currently paying" for the purpose of
# provisioning compute. `past_due` is excluded — Stripe is actively trying
# to recover payment, and we'd rather refuse new infra than rack up cost
# against a card that's failing.
_PROVISION_OK_STATUSES = frozenset({"active", "trialing"})


async def _assert_provision_allowed(owner_id: str, clerk_user_id: str) -> None:
    """Raise 402 if the owner cannot afford to provision a new container.

    Two layers of gating:

    1. Subscription. A canceled, incomplete, unpaid, paused, or past_due
       subscription cannot spin up new compute — that's how we prevent
       arbitrary signed-in users from minting free ECS Fargate tasks
       (audit C1). Two cases pass:
         - ``subscription_status`` is ``active`` or ``trialing``.
         - Legacy row pre-Plan-3: ``stripe_subscription_id`` is set but
           ``subscription_status`` hasn't been backfilled yet. We mirror
           ``gate_chat``'s leniency here so a deploy doesn't 402 paying
           customers mid-migration. Codex P1 on PR #488.
       Anything else (no row at all, or status set to a non-OK value)
       gets 402.
    2. For ``bedrock_claude``, the credit balance must be > 0. A
       container with $0 prepaid credits is dead weight: ``gate_chat``
       blocks every chat anyway, so the user can't use it. Refuse the
       provision instead of leaking ECS cost.
    """
    account = await billing_repo.get_by_owner_id(owner_id)
    if not account:
        raise HTTPException(status_code=402, detail="Active subscription required")
    status = account.get("subscription_status")
    has_legacy_sub = bool(account.get("stripe_subscription_id"))
    # Allow if status is in the OK set, OR if status is unset on a row
    # that has a stripe_subscription_id (legacy / pre-backfill).
    is_ok = status in _PROVISION_OK_STATUSES or (status is None and has_legacy_sub)
    if not is_ok:
        raise HTTPException(status_code=402, detail="Active subscription required")

    provider_choice, _ = await _resolve_provider_choice(clerk_user_id)
    if provider_choice == "bedrock_claude":
        from core.services import credit_ledger

        balance = await credit_ledger.get_balance(clerk_user_id)
        if balance <= 0:
            raise HTTPException(
                status_code=402,
                detail="Top up Claude credits before provisioning",
            )


async def _resolve_provider_choice(clerk_user_id: str) -> tuple[str, str | None]:
    """Look up the user's saved provider_choice (+ byo_provider when applicable).

    Always reads ``user_repo`` by the *Clerk user id* (not owner_id) — in
    org context, the org_id has no provider_choice row, so passing it
    would silently fall back to bedrock_claude and provision the wrong
    LLM config for chatgpt_oauth/byo_key users. Codex P1 on PR #393.

    Falls back to ``bedrock_claude`` when the row exists but no choice is
    persisted yet — that matches the old default and keeps recovery working
    for users who provisioned before Plan 3 introduced the field.
    """
    row = await user_repo.get(clerk_user_id)
    provider_choice = (row or {}).get("provider_choice") or "bedrock_claude"
    byo_provider = (row or {}).get("byo_provider") if provider_choice == "byo_key" else None
    return provider_choice, byo_provider


async def _background_provision(owner_id: str, clerk_user_id: str) -> None:
    """Run provisioning in the background.

    ``owner_id`` is the container scope (org_id in org context, user_id in
    personal). ``clerk_user_id`` is the calling Clerk user — used to look
    up provider_choice. In personal context they are the same; in org
    context they differ.

    Also kicks off Paperclip workspace provisioning so the /teams UI works
    on first visit. Paperclip failure does NOT abort container
    provisioning — the user can retry from /teams.
    """
    try:
        provider_choice, byo_provider = await _resolve_provider_choice(clerk_user_id)
        await get_ecs_manager().provision_user_container(
            owner_id,
            provider_choice=provider_choice,
            byo_provider=byo_provider,
        )
    except Exception:
        logger.exception("Background provisioning failed for owner %s", owner_id)
        return
    await _ensure_paperclip_workspace(owner_id=owner_id, clerk_user_id=clerk_user_id)


async def _ensure_paperclip_workspace(*, owner_id: str, clerk_user_id: str) -> None:
    """Provision the Paperclip company for this owner if it doesn't exist.

    Personal context: ``owner_id == clerk_user_id`` and we use the user's
    own id as the Paperclip ``org_id``. Org context: Clerk's
    ``organization.created`` webhook (in ``routers/webhooks.py``) is the
    canonical entry point — we skip here so we don't race the webhook
    or create a personal-shaped row for an org owner.

    Idempotent: ``PaperclipProvisioning.provision_org`` short-circuits on
    an existing ``status="active"`` row, so calling this from every
    container-provision path is safe.
    """
    if owner_id != clerk_user_id:
        return
    try:
        from core.services.paperclip_owner_email import lookup_owner_email
        from routers.webhooks import _close_paperclip_http, _get_paperclip_provisioning

        owner_email = await lookup_owner_email(org_id=None, fallback_user_id=clerk_user_id)
        if not owner_email:
            logger.warning(
                "paperclip auto-provision skipped: no email for user %s",
                clerk_user_id,
            )
            return
        provisioning = await _get_paperclip_provisioning()
        try:
            await provisioning.provision_org(
                org_id=clerk_user_id,
                owner_user_id=clerk_user_id,
                owner_email=owner_email,
            )
        finally:
            await _close_paperclip_http(provisioning)
    except Exception:
        logger.exception(
            "Paperclip auto-provision failed for user %s — user can retry from /teams",
            clerk_user_id,
        )


@router.get(
    "/status",
    summary="Get container metadata for current user",
    description=(
        "Returns the user's container status and metadata. "
        "If the container is in error state and the user has an active "
        "subscription, auto-triggers re-provisioning in the background."
    ),
    operation_id="container_status",
    responses={
        404: {"description": "No container for this user"},
    },
)
async def container_status(
    auth: AuthContext = Depends(get_current_user),
):
    owner_id = resolve_owner_id(auth)
    ecs_manager = get_ecs_manager()
    # Use resolve_running_container so polling triggers the
    # provisioning -> running health-check transition.
    container, _ip = await ecs_manager.resolve_running_container(owner_id)
    if not container:
        # Fall back to get_service_status for error/stopped containers
        container = await ecs_manager.get_service_status(owner_id)
    if not container:
        raise HTTPException(status_code=404, detail="No container found")

    # Auto-retry: if container is in a failed/stuck state AND the owner can
    # currently afford to provision, trigger re-provisioning in the
    # background. The same gate as /provision (audit C1) — bare
    # subscription-id existence wasn't enough; we need active/trialing
    # status, and bedrock_claude users need a positive credit balance.
    retryable_states = ("error", "stopped")
    if container.get("status") in retryable_states:
        try:
            await _assert_provision_allowed(owner_id, auth.user_id)
        except HTTPException:
            pass
        else:
            await container_repo.update_status(owner_id, "provisioning", "auto_retry")
            asyncio.create_task(_background_provision(owner_id, auth.user_id))
            container["status"] = "provisioning"
            container["substatus"] = "auto_retry"

    return {
        "service_name": container.get("service_name"),
        "status": container.get("status"),
        "substatus": container.get("substatus"),
        "created_at": container.get("created_at"),
        "updated_at": container.get("updated_at"),
        "region": settings.AWS_REGION,
        "last_error": container.get("last_error"),
        "last_error_at": container.get("last_error_at"),
        # Cold-start phase for the frontend stepper. See
        # _resolve_cold_start_phase for the (status, pool) -> phase map.
        "phase": _safe_phase(container, owner_id),
    }


def _safe_phase(container: dict, owner_id: str) -> str:
    """Wrap _resolve_cold_start_phase so a not-yet-initialized gateway
    pool doesn't 500 the status endpoint. Status must always answer.

    On pool init failure (ManagementApiClientError when
    WS_MANAGEMENT_API_URL is unset — typically test envs that skip the
    lifespan handler) we fall back to a *container-only* phase mapping
    instead of forcing "starting":

      - ECS RUNNING  -> "ready"        (best guess; chat may or may
                                        not work — but the frontend will
                                        surface the real chat error
                                        instead of trapping the user
                                        in a never-ending stepper)
      - anything else -> "provisioning"

    Codex P1 on PR #461: returning "starting" here keeps users stuck
    in the cold-start UI indefinitely even when the container itself
    is healthy and usable.

    Anything other than ManagementApiClientError bubbles up as a real
    bug. Logs once per process so a production misconfiguration shows
    up in CloudWatch.
    """
    try:
        pool = get_gateway_pool()
    except ManagementApiClientError as exc:
        if not getattr(_safe_phase, "_pool_warning_logged", False):
            logger.warning(
                "Gateway pool not initialized; status phase falls back to container-only mapping. Real pool error: %s",
                exc,
            )
            _safe_phase._pool_warning_logged = True  # type: ignore[attr-defined]
        return "ready" if (container or {}).get("status") == "running" else "provisioning"
    return _resolve_cold_start_phase(container, pool, owner_id)


@router.post(
    "/provision",
    summary="Provision a container for the current owner",
    description=(
        "Creates a new container for the authenticated owner (user or org). "
        "Idempotent — returns existing container if one already exists. "
        "Only provisions for the resolved owner_id (org in org context, user in personal)."
    ),
    operation_id="container_provision",
    responses={
        200: {"description": "Container provisioned or already exists"},
        503: {"description": "Provisioning failed"},
    },
)
async def container_provision(
    auth: AuthContext = Depends(get_current_user),
):
    owner_id = resolve_owner_id(auth)

    # Check if container already exists (idempotent). The payment gate
    # below is intentionally NOT applied to existing containers — billing
    # state can churn (cancel + resubscribe) and we don't want a stale
    # 402 to mask the actual container the caller is asking about.
    existing = await container_repo.get_by_owner_id(owner_id)
    if existing:
        if existing.get("status") == "stopped":
            # Container was scaled to zero -- restart it. This is the
            # cold-start path; emit a metric so we can answer "how often do
            # users hit a cold start" and "how long does the restart take".
            try:
                with timing("gateway.cold_start.latency"):
                    await get_ecs_manager().start_user_service(owner_id)
                put_metric("gateway.cold_start.count", dimensions={"outcome": "ok"})
                logger.info("Restarted stopped container for owner %s", owner_id)
                return {
                    "status": "provisioning",
                    "service_name": existing.get("service_name"),
                    "owner_id": owner_id,
                    "already_existed": True,
                }
            except EcsManagerError as e:
                put_metric("gateway.cold_start.count", dimensions={"outcome": "error"})
                logger.error("Restart failed for stopped container, owner %s: %s", owner_id, e)
                raise HTTPException(status_code=503, detail=str(e))
        return {
            "status": existing.get("status", "unknown"),
            "service_name": existing.get("service_name"),
            "owner_id": owner_id,
            "already_existed": True,
        }

    # Payment gate (audit C1). New-container path only — the existing-
    # container branch above intentionally bypasses this so we don't 402
    # callers asking about a container they already have.
    await _assert_provision_allowed(owner_id, auth.user_id)

    # Provision new container — read the user's saved provider_choice so the
    # container is configured for the right LLM path (OAuth / BYO key /
    # bedrock_claude). Codex P1 on PR #393.
    try:
        provider_choice, byo_provider = await _resolve_provider_choice(auth.user_id)
        service_name = await get_ecs_manager().provision_user_container(
            owner_id,
            provider_choice=provider_choice,
            byo_provider=byo_provider,
        )
        logger.info("Provisioned container %s for owner %s", service_name, owner_id)
        asyncio.create_task(_ensure_paperclip_workspace(owner_id=owner_id, clerk_user_id=auth.user_id))
        return {
            "status": "provisioning",
            "service_name": service_name,
            "owner_id": owner_id,
            "already_existed": False,
        }
    except EcsManagerError as e:
        logger.error("Provisioning failed for owner %s: %s", owner_id, e)
        raise HTTPException(status_code=503, detail=str(e))


@router.post(
    "/retry",
    summary="Retry provisioning for a failed container",
    description=(
        "Retries the full provisioning flow for a container that is in error state. Requires an active subscription."
    ),
    operation_id="container_retry",
    responses={
        404: {"description": "No container for this user"},
        409: {"description": "Container is not in error state"},
        402: {"description": "No active subscription"},
    },
)
async def container_retry(
    auth: AuthContext = Depends(get_current_user),
):
    owner_id = resolve_owner_id(auth)
    # Audit C1: same hardened gate as /provision — ID existence isn't
    # enough; status must be active/trialing AND bedrock_claude needs
    # a positive credit balance.
    await _assert_provision_allowed(owner_id, auth.user_id)

    ecs_manager = get_ecs_manager()
    container = await ecs_manager.get_service_status(owner_id)
    if not container:
        raise HTTPException(status_code=404, detail="No container found")
    if container.get("status") not in ("error", "stopped"):
        raise HTTPException(
            status_code=409,
            detail=f"Container is in '{container.get('status')}' state, not retryable",
        )

    try:
        provider_choice, byo_provider = await _resolve_provider_choice(auth.user_id)
        service_name = await ecs_manager.provision_user_container(
            owner_id,
            provider_choice=provider_choice,
            byo_provider=byo_provider,
        )
    except EcsManagerError as e:
        logger.error("Retry provisioning failed for owner %s: %s", owner_id, e)
        raise HTTPException(status_code=502, detail="Provisioning failed")

    asyncio.create_task(_ensure_paperclip_workspace(owner_id=owner_id, clerk_user_id=auth.user_id))
    return {"ok": True, "service_name": service_name}
