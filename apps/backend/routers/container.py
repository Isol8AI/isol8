"""Container lifecycle management endpoints.

Provides container status (with auto-retry for failed containers)
and a manual retry-provision endpoint.
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException

from core.auth import AuthContext, get_current_user, resolve_owner_id
from core.config import settings
from core.containers import get_ecs_manager
from core.containers.ecs_manager import EcsManagerError
from core.observability.metrics import put_metric, timing
from core.repositories import billing_repo, container_repo, user_repo

logger = logging.getLogger(__name__)

router = APIRouter()


async def _owner_has_subscription(owner_id: str) -> bool:
    """Check if an owner has an active billing subscription."""
    account = await billing_repo.get_by_owner_id(owner_id)
    return account is not None and account.get("stripe_subscription_id") is not None


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

    # Auto-retry: if container is in a failed/stuck state and user has a subscription,
    # trigger re-provisioning in the background.
    retryable_states = ("error", "stopped")
    if container.get("status") in retryable_states and await _owner_has_subscription(owner_id):
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
    }


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

    # Check if container already exists (idempotent)
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
    if not await _owner_has_subscription(owner_id):
        raise HTTPException(status_code=402, detail="Active subscription required")

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

    return {"ok": True, "service_name": service_name}
