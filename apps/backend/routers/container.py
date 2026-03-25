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
from core.repositories import billing_repo, container_repo

logger = logging.getLogger(__name__)

router = APIRouter()


async def _user_has_subscription(user_id: str) -> bool:
    """Check if a user has an active billing subscription."""
    account = await billing_repo.get_by_clerk_user_id(user_id)
    return account is not None and account.get("stripe_subscription_id") is not None


async def _background_provision(user_id: str) -> None:
    """Run provisioning in the background."""
    try:
        await get_ecs_manager().provision_user_container(user_id)
    except Exception:
        logger.exception("Background provisioning failed for user %s", user_id)


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
    if container.get("status") in retryable_states and await _user_has_subscription(auth.user_id):
        await container_repo.update_status(owner_id, "provisioning", "auto_retry")
        asyncio.create_task(_background_provision(owner_id))
        container["status"] = "provisioning"
        container["substatus"] = "auto_retry"

    return {
        "service_name": container.get("service_name"),
        "status": container.get("status"),
        "substatus": container.get("substatus"),
        "created_at": container.get("created_at"),
        "updated_at": container.get("updated_at"),
        "region": settings.AWS_REGION,
    }


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
    if not await _user_has_subscription(auth.user_id):
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
        service_name = await ecs_manager.provision_user_container(owner_id)
    except EcsManagerError as e:
        logger.error("Retry provisioning failed for owner %s: %s", owner_id, e)
        raise HTTPException(status_code=502, detail="Provisioning failed")

    return {"ok": True, "service_name": service_name}
