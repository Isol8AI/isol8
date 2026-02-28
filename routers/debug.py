"""
Dev-only container provisioning endpoints.

Bypasses Stripe for local testing — disabled in production.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth import AuthContext, get_current_user
from core.config import settings
from core.containers import get_container_manager
from core.containers.manager import ContainerError

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/provision",
    summary="Provision container (dev only)",
    description=(
        "Manually provisions a container for the authenticated user. "
        "Only available in non-production environments for local testing."
    ),
    operation_id="debug_provision_container",
    responses={
        403: {"description": "Not available in production"},
        409: {"description": "Container already running"},
        503: {"description": "Docker not available or provisioning failed"},
    },
)
async def provision_container(auth: AuthContext = Depends(get_current_user)):
    if settings.ENVIRONMENT == "prod":
        raise HTTPException(status_code=403, detail="Not available in production")

    cm = get_container_manager()
    if not cm.available:
        raise HTTPException(status_code=503, detail="Docker not available")

    existing_port = cm.get_container_port(auth.user_id)
    if existing_port:
        return {
            "status": "already_running",
            "port": existing_port,
            "user_id": auth.user_id,
        }

    try:
        info = cm.provision_container(auth.user_id)
        return {
            "status": "provisioned",
            "port": info.port,
            "container_id": info.container_id,
            "user_id": auth.user_id,
        }
    except ContainerError as e:
        logger.error("Dev provision failed for user %s: %s", auth.user_id, e)
        raise HTTPException(status_code=503, detail=str(e))


@router.delete(
    "/provision",
    summary="Remove container (dev only)",
    description="Removes the user's container and optionally its volume. Dev only.",
    operation_id="debug_remove_container",
    responses={
        403: {"description": "Not available in production"},
        404: {"description": "No container found"},
    },
)
async def remove_container(
    keep_volume: bool = Query(True, description="Preserve workspace volume"),
    auth: AuthContext = Depends(get_current_user),
):
    if settings.ENVIRONMENT == "prod":
        raise HTTPException(status_code=403, detail="Not available in production")

    cm = get_container_manager()
    removed = cm.remove_container(auth.user_id, keep_volume=keep_volume)
    if not removed:
        raise HTTPException(status_code=404, detail="No container found")
    return {"status": "removed", "volume_kept": keep_volume}
