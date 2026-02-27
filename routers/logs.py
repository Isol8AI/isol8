"""
Log viewing API for user's OpenClaw container.

Requires a dedicated container — returns 404 for free-tier users.
Uses Docker container logs API for log retrieval.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth import AuthContext, get_current_user
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


@router.get(
    "",
    summary="Get container logs",
    description="Returns recent logs from the user's container.",
    operation_id="get_logs",
    responses={404: {"description": "No container (free tier)"}},
)
async def get_logs(
    lines: int = Query(100, ge=1, le=1000, description="Number of log lines"),
    auth: AuthContext = Depends(get_current_user),
):
    _require_container(auth.user_id)
    cm = get_container_manager()
    try:
        raw = cm.get_container_logs(auth.user_id, tail=lines)
    except ContainerError as e:
        logger.error("Failed to get logs for user %s: %s", auth.user_id, e)
        raise HTTPException(status_code=502, detail="Failed to retrieve logs")
    log_lines = [line for line in raw.strip().split("\n") if line]
    return {"logs": raw, "lines": len(log_lines)}
