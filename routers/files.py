"""
File management API for user's OpenClaw container workspace.

Requires a dedicated container — returns 404 for free-tier users.
All operations exec commands inside the user's Docker container.
"""

import logging
import posixpath
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel

from core.auth import AuthContext, get_current_user
from core.containers import get_container_manager
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


def _validate_path(path: str) -> str:
    """Validate and normalize a file path to prevent traversal attacks."""
    # Normalize the path and check for traversal
    normalized = posixpath.normpath(path)
    if normalized.startswith("..") or "/../" in f"/{normalized}/" or normalized.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid path: directory traversal not allowed")
    return normalized


class FileContent(BaseModel):
    """Request body for file upload."""

    content: str


# =============================================================================
# Workspace files
# =============================================================================


@router.get(
    "/workspace",
    summary="List workspace files",
    description="Lists files and directories in the workspace root or a subdirectory.",
    operation_id="list_workspace",
    responses={404: {"description": "No container (free tier)"}},
)
async def list_workspace(
    path: Optional[str] = Query(None, description="Subdirectory path"),
    auth: AuthContext = Depends(get_current_user),
):
    _require_container(auth.user_id)

    target = _WORKSPACE
    if path:
        safe_path = _validate_path(path)
        target = f"{_WORKSPACE}/{safe_path}"

    raw = _exec(auth.user_id, ["ls", "-1", target])
    files = [f for f in raw.strip().split("\n") if f]
    return {"files": files, "path": path or "/"}


@router.get(
    "/workspace/{path:path}",
    summary="Get file content",
    description="Downloads a file from the workspace.",
    operation_id="get_workspace_file",
    responses={
        400: {"description": "Invalid path"},
        404: {"description": "No container (free tier)"},
    },
)
async def get_workspace_file(
    path: str,
    auth: AuthContext = Depends(get_current_user),
):
    _require_container(auth.user_id)
    safe_path = _validate_path(path)
    content = _exec(auth.user_id, ["cat", f"{_WORKSPACE}/{safe_path}"])
    return {"content": content, "path": safe_path}


@router.put(
    "/workspace/{path:path}",
    summary="Upload file",
    description="Uploads or overwrites a file in the workspace.",
    operation_id="put_workspace_file",
    responses={
        400: {"description": "Invalid path"},
        404: {"description": "No container (free tier)"},
    },
)
async def put_workspace_file(
    path: str,
    body: FileContent,
    auth: AuthContext = Depends(get_current_user),
):
    _require_container(auth.user_id)
    safe_path = _validate_path(path)

    import base64

    encoded = base64.b64encode(body.content.encode()).decode()

    # Ensure parent directory exists, then write file
    parent = posixpath.dirname(f"{_WORKSPACE}/{safe_path}")
    _exec(auth.user_id, ["mkdir", "-p", parent])
    _exec(
        auth.user_id,
        [
            "sh",
            "-c",
            f"echo '{encoded}' | base64 -d > {_WORKSPACE}/{safe_path}",
        ],
    )
    return {"path": safe_path, "status": "ok"}


@router.delete(
    "/workspace/{path:path}",
    status_code=204,
    summary="Delete file",
    description="Deletes a file from the workspace.",
    operation_id="delete_workspace_file",
    responses={
        400: {"description": "Invalid path"},
        404: {"description": "No container (free tier)"},
    },
)
async def delete_workspace_file(
    path: str,
    auth: AuthContext = Depends(get_current_user),
):
    _require_container(auth.user_id)
    safe_path = _validate_path(path)
    _exec(auth.user_id, ["rm", "-f", f"{_WORKSPACE}/{safe_path}"])
    return Response(status_code=204)


# =============================================================================
# Agent-specific files
# =============================================================================


@router.get(
    "/agents/{agent_name}",
    summary="List agent files",
    description="Lists files in a specific agent's directory.",
    operation_id="list_agent_files",
    responses={401: {"description": "Unauthorized"}, 404: {"description": "No container (free tier)"}},
)
async def list_agent_files(
    agent_name: str,
    auth: AuthContext = Depends(get_current_user),
):
    _require_container(auth.user_id)
    raw = _exec(auth.user_id, ["ls", "-1", f"{_WORKSPACE}/agents/{agent_name}"])
    files = [f for f in raw.strip().split("\n") if f]
    return {"files": files, "agent": agent_name}


@router.put(
    "/agents/{agent_name}/{path:path}",
    summary="Upload agent file",
    description="Uploads a file to an agent's directory.",
    operation_id="put_agent_file",
    responses={
        400: {"description": "Invalid path"},
        401: {"description": "Unauthorized"},
        404: {"description": "No container (free tier)"},
    },
)
async def put_agent_file(
    agent_name: str,
    path: str,
    body: FileContent,
    auth: AuthContext = Depends(get_current_user),
):
    _require_container(auth.user_id)
    safe_path = _validate_path(path)

    import base64

    encoded = base64.b64encode(body.content.encode()).decode()

    target_dir = f"{_WORKSPACE}/agents/{agent_name}"
    parent = posixpath.dirname(f"{target_dir}/{safe_path}")
    _exec(auth.user_id, ["mkdir", "-p", parent])
    _exec(
        auth.user_id,
        [
            "sh",
            "-c",
            f"echo '{encoded}' | base64 -d > {target_dir}/{safe_path}",
        ],
    )
    return {"path": f"agents/{agent_name}/{safe_path}", "status": "ok"}
