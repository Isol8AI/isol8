"""REST endpoints for browsing agent workspace files on EFS."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth import AuthContext, get_current_user, resolve_owner_id
from core.containers import get_workspace
from core.containers.workspace import WorkspaceError

logger = logging.getLogger(__name__)

router = APIRouter()


def _agent_workspace_path(owner_id: str, agent_id: str) -> str:
    """Build the relative path to an agent's workspace within the user dir."""
    if "/" in agent_id or "\\" in agent_id or ".." in agent_id:
        raise HTTPException(status_code=400, detail="Invalid agent_id")
    return f"agents/{agent_id}"


@router.get("/workspace/{agent_id}/tree")
async def list_workspace_tree(
    agent_id: str,
    path: str = Query("", description="Subdirectory path relative to agent workspace"),
    auth: AuthContext = Depends(get_current_user),
):
    """List files and directories in an agent's workspace."""
    owner_id = resolve_owner_id(auth)
    workspace = get_workspace()

    agent_base = _agent_workspace_path(owner_id, agent_id)
    full_path = f"{agent_base}/{path}" if path else agent_base

    try:
        entries = workspace.list_directory(owner_id, full_path)
    except WorkspaceError as exc:
        if "not found" in str(exc).lower():
            raise HTTPException(status_code=404, detail=str(exc))
        if "traversal" in str(exc).lower():
            raise HTTPException(status_code=403, detail="Access denied")
        raise HTTPException(status_code=500, detail=str(exc))

    return {"files": entries}


@router.get("/workspace/{agent_id}/file")
async def read_workspace_file(
    agent_id: str,
    path: str = Query(..., description="File path relative to agent workspace"),
    auth: AuthContext = Depends(get_current_user),
):
    """Read a file's content and metadata from an agent's workspace."""
    owner_id = resolve_owner_id(auth)
    workspace = get_workspace()

    agent_base = _agent_workspace_path(owner_id, agent_id)
    full_path = f"{agent_base}/{path}"

    try:
        info = workspace.read_file_info(owner_id, full_path)
    except WorkspaceError as exc:
        if "not found" in str(exc).lower():
            raise HTTPException(status_code=404, detail=str(exc))
        if "traversal" in str(exc).lower():
            raise HTTPException(status_code=403, detail="Access denied")
        raise HTTPException(status_code=500, detail=str(exc))

    return info
