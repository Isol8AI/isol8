"""Container lifecycle management endpoints.

Provides container status (with auto-retry for failed containers)
and a manual retry-provision endpoint.
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import AuthContext, get_current_user
from core.config import settings
from core.containers import get_ecs_manager
from core.containers.ecs_manager import EcsManagerError
from core.database import get_db, get_session_factory
from models.billing import BillingAccount

logger = logging.getLogger(__name__)

router = APIRouter()


async def _user_has_subscription(user_id: str, db: AsyncSession) -> bool:
    """Check if a user has an active billing subscription."""
    result = await db.execute(select(BillingAccount).where(BillingAccount.clerk_user_id == user_id))
    account = result.scalar_one_or_none()
    return account is not None and account.stripe_subscription_id is not None


async def _background_provision(user_id: str) -> None:
    """Run provisioning in the background using a fresh DB session."""
    try:
        session_factory = get_session_factory()
        async with session_factory() as db:
            await get_ecs_manager().provision_user_container(user_id, db)
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
    db: AsyncSession = Depends(get_db),
):
    ecs_manager = get_ecs_manager()
    # Use resolve_running_container so polling triggers the
    # provisioning -> running health-check transition.
    container, _ip = await ecs_manager.resolve_running_container(auth.user_id, db)
    if not container:
        # Fall back to get_service_status for error/stopped containers
        container = await ecs_manager.get_service_status(auth.user_id, db)
    if not container:
        raise HTTPException(status_code=404, detail="No container found")

    # Auto-retry: if container is in error state and user has a subscription,
    # trigger re-provisioning in the background.
    if container.status == "error" and await _user_has_subscription(auth.user_id, db):
        container.status = "provisioning"
        container.substatus = None
        await db.commit()
        asyncio.create_task(_background_provision(auth.user_id))

    return {
        "service_name": container.service_name,
        "status": container.status,
        "substatus": container.substatus,
        "created_at": container.created_at.isoformat() if container.created_at else None,
        "updated_at": container.updated_at.isoformat() if container.updated_at else None,
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
    db: AsyncSession = Depends(get_db),
):
    if not await _user_has_subscription(auth.user_id, db):
        raise HTTPException(status_code=402, detail="Active subscription required")

    ecs_manager = get_ecs_manager()
    container = await ecs_manager.get_service_status(auth.user_id, db)
    if not container:
        raise HTTPException(status_code=404, detail="No container found")
    if container.status not in ("error", "stopped"):
        raise HTTPException(
            status_code=409,
            detail=f"Container is in '{container.status}' state, not retryable",
        )

    try:
        service_name = await ecs_manager.provision_user_container(auth.user_id, db)
    except EcsManagerError as e:
        logger.error("Retry provisioning failed for user %s: %s", auth.user_id, e)
        raise HTTPException(status_code=502, detail="Provisioning failed")

    return {"ok": True, "service_name": service_name}
