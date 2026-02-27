"""
Settings API for managing user's OpenClaw container configuration.

Requires a dedicated container — returns 404 for free-tier users.
All operations exec commands inside the user's Docker container.
"""

import json
import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Response

from core.auth import AuthContext, get_current_user
from core.containers import get_container_manager
from core.containers.config import patch_openclaw_config
from core.containers.manager import ContainerError

logger = logging.getLogger(__name__)

router = APIRouter()

_WORKSPACE = "/home/node/.openclaw"


def _require_container(user_id: str) -> int:
    """Get container port or raise 404."""
    cm = get_container_manager()
    port = cm.get_container_port(user_id)
    if not port:
        raise HTTPException(status_code=404, detail="No container found. Upgrade to a paid plan.")
    return port


def _exec(user_id: str, command: list[str]) -> str:
    """Exec command in user's container."""
    cm = get_container_manager()
    try:
        return cm.exec_command(user_id, command)
    except ContainerError as e:
        logger.error("Container exec failed for user %s: %s", user_id, e)
        raise HTTPException(status_code=502, detail="Container command failed")


def _read_config(user_id: str) -> dict:
    """Read openclaw.json from the user's container."""
    raw = _exec(user_id, ["cat", f"{_WORKSPACE}/openclaw.json"])
    return json.loads(raw)


# =============================================================================
# Config
# =============================================================================


@router.get(
    "/config",
    summary="Get container config",
    description="Returns the user's openclaw.json configuration (credentials stripped).",
    operation_id="get_config",
    responses={404: {"description": "No container (free tier)"}},
)
async def get_config(auth: AuthContext = Depends(get_current_user)):
    _require_container(auth.user_id)
    config = _read_config(auth.user_id)
    # Strip sensitive fields
    for provider in config.get("models", {}).get("providers", {}).values():
        provider.pop("apiKey", None)
    return {"config": config}


@router.put(
    "/config",
    summary="Update container config",
    description="Deep-merges partial config updates into the user's openclaw.json.",
    operation_id="update_config",
    responses={404: {"description": "No container (free tier)"}},
)
async def update_config(
    updates: Dict[str, Any],
    auth: AuthContext = Depends(get_current_user),
):
    _require_container(auth.user_id)
    existing = _read_config(auth.user_id)
    merged = patch_openclaw_config(existing, updates)
    merged_json = json.dumps(merged, indent=2)

    import base64

    encoded = base64.b64encode(merged_json.encode()).decode()
    _exec(
        auth.user_id,
        [
            "sh",
            "-c",
            f"echo '{encoded}' | base64 -d > {_WORKSPACE}/openclaw.json",
        ],
    )
    return {"config": merged}


# =============================================================================
# Models
# =============================================================================


@router.get(
    "/models",
    summary="Get model configuration",
    description="Returns configured models and providers.",
    operation_id="get_models",
    responses={404: {"description": "No container (free tier)"}},
)
async def get_models(auth: AuthContext = Depends(get_current_user)):
    _require_container(auth.user_id)
    config = _read_config(auth.user_id)
    models = config.get("models", {})
    return {
        "providers": models.get("providers", {}),
        "bedrockDiscovery": models.get("bedrockDiscovery", {}),
    }


# =============================================================================
# Tools
# =============================================================================


@router.get(
    "/tools",
    summary="Get tool configuration",
    description="Returns configured tools and browser settings.",
    operation_id="get_tools",
    responses={404: {"description": "No container (free tier)"}},
)
async def get_tools(auth: AuthContext = Depends(get_current_user)):
    _require_container(auth.user_id)
    config = _read_config(auth.user_id)
    return {
        "tools": config.get("tools", {}),
        "browser": config.get("browser", {}),
    }


# =============================================================================
# Memory
# =============================================================================


@router.get(
    "/memory",
    summary="List memory entries",
    description="Lists memory entries from the user's container.",
    operation_id="list_memory",
    responses={404: {"description": "No container (free tier)"}},
)
async def list_memory(auth: AuthContext = Depends(get_current_user)):
    _require_container(auth.user_id)
    raw = _exec(auth.user_id, ["openclaw", "memory", "list", "--json"])
    try:
        entries = json.loads(raw)
    except json.JSONDecodeError:
        entries = []
    return {"entries": entries}


@router.delete(
    "/memory/{memory_id}",
    status_code=204,
    summary="Delete memory entry",
    description="Deletes a memory entry by ID.",
    operation_id="delete_memory",
    responses={404: {"description": "No container (free tier)"}},
)
async def delete_memory(
    memory_id: str,
    auth: AuthContext = Depends(get_current_user),
):
    _require_container(auth.user_id)
    _exec(auth.user_id, ["openclaw", "memory", "delete", "--id", memory_id])
    return Response(status_code=204)


# =============================================================================
# Sessions
# =============================================================================


@router.get(
    "/sessions",
    summary="List sessions",
    description="Lists chat sessions from the user's container.",
    operation_id="list_sessions",
    responses={404: {"description": "No container (free tier)"}},
)
async def list_sessions(auth: AuthContext = Depends(get_current_user)):
    _require_container(auth.user_id)
    raw = _exec(auth.user_id, ["openclaw", "session", "list", "--json"])
    try:
        sessions = json.loads(raw)
    except json.JSONDecodeError:
        sessions = []
    return {"sessions": sessions}


@router.delete(
    "/sessions/{session_id}",
    status_code=204,
    summary="Delete session",
    description="Deletes a chat session by ID.",
    operation_id="delete_session",
    responses={404: {"description": "No container (free tier)"}},
)
async def delete_session(
    session_id: str,
    auth: AuthContext = Depends(get_current_user),
):
    _require_container(auth.user_id)
    _exec(auth.user_id, ["openclaw", "session", "delete", "--id", session_id])
    return Response(status_code=204)
