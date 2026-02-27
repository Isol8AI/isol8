"""
Debug and health API for user's OpenClaw container.

Requires a dedicated container — returns 404 for free-tier users.
Includes dev-only provisioning endpoint for local testing.
"""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth import AuthContext, get_current_user
from core.config import settings
from core.containers import get_container_manager
from core.containers.manager import ContainerError

logger = logging.getLogger(__name__)

router = APIRouter()


def _require_container(user_id: str) -> int:
    cm = get_container_manager()
    port = cm.get_container_port(user_id)
    if not port:
        raise HTTPException(status_code=404, detail="No container found. Upgrade to a paid plan.")
    return port


def _exec(user_id: str, command: list[str]) -> str:
    cm = get_container_manager()
    try:
        return cm.exec_command(user_id, command)
    except ContainerError as e:
        logger.error("Container exec failed for user %s: %s", user_id, e)
        raise HTTPException(status_code=502, detail="Container command failed")


@router.get(
    "/status",
    summary="Container status",
    description="Returns a status snapshot of the user's container.",
    operation_id="get_debug_status",
    responses={404: {"description": "No container (free tier)"}},
)
async def get_status(auth: AuthContext = Depends(get_current_user)):
    _require_container(auth.user_id)
    raw = _exec(auth.user_id, ["openclaw", "status", "--json"])
    try:
        status = json.loads(raw)
    except json.JSONDecodeError:
        status = {"raw": raw}
    return {"status": status}


@router.get(
    "/health",
    summary="Container health check",
    description="Checks if the user's container gateway is healthy.",
    operation_id="get_debug_health",
    responses={404: {"description": "No container (free tier)"}},
)
async def get_health(auth: AuthContext = Depends(get_current_user)):
    _require_container(auth.user_id)
    cm = get_container_manager()
    healthy = cm.is_healthy(auth.user_id)
    return {"healthy": healthy}


@router.get(
    "/models",
    summary="List available models",
    description="Returns models available in the user's container.",
    operation_id="get_debug_models",
    responses={404: {"description": "No container (free tier)"}},
)
async def get_models(auth: AuthContext = Depends(get_current_user)):
    _require_container(auth.user_id)
    raw = _exec(auth.user_id, ["openclaw", "model", "list", "--json"])
    try:
        models = json.loads(raw)
    except json.JSONDecodeError:
        models = []
    return {"models": models}


@router.get(
    "/events",
    summary="Recent events",
    description="Returns recent event log from the user's container.",
    operation_id="get_debug_events",
    responses={404: {"description": "No container (free tier)"}},
)
async def get_events(
    limit: int = Query(50, ge=1, le=200),
    auth: AuthContext = Depends(get_current_user),
):
    _require_container(auth.user_id)
    raw = _exec(auth.user_id, ["openclaw", "event", "list", "--json", "--limit", str(limit)])
    try:
        events = json.loads(raw)
    except json.JSONDecodeError:
        events = []
    return {"events": events}


# =============================================================================
# Dev-only provisioning (bypasses Stripe for local testing)
# =============================================================================


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
