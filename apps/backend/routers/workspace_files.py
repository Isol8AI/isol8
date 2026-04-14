"""REST endpoints for browsing agent workspace files on EFS."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from core.auth import AuthContext, get_current_user, resolve_owner_id
from core.containers import get_workspace
from core.containers.workspace import WorkspaceError

logger = logging.getLogger(__name__)

router = APIRouter()


def _agent_workspace_path(owner_id: str, agent_id: str) -> str:
    """Build the relative path to an agent's workspace within the user dir."""
    if "/" in agent_id or "\\" in agent_id or ".." in agent_id:
        raise HTTPException(status_code=400, detail="Invalid agent_id")
    return f"workspaces/{agent_id}"


def _collect_recursive(workspace, owner_id: str, path: str, entries: list, max_depth: int = 10):
    """Recursively collect file entries up to max_depth."""
    if max_depth <= 0:
        return
    try:
        items = workspace.list_directory(owner_id, path)
    except WorkspaceError:
        return
    for item in items:
        entries.append(item)
        if item["type"] == "dir":
            _collect_recursive(workspace, owner_id, item["path"], entries, max_depth - 1)


CONFIG_ALLOWLIST: set[str] = {
    "SOUL.md",
    "MEMORY.md",
    "TOOLS.md",
    "IDENTITY.md",
    "USER.md",
    "HEARTBEAT.md",
    "BOOTSTRAP.md",
    "AGENTS.md",
}


def _list_config_files(workspace, owner_id: str, agent_id: str) -> list[dict]:
    """List only allowlisted config files from agents/{agent_id}/."""
    if "/" in agent_id or "\\" in agent_id or ".." in agent_id:
        return []
    user_root = workspace.user_path(owner_id)
    agent_dir = user_root / "agents" / agent_id
    if not agent_dir.exists() or not agent_dir.is_dir():
        return []
    results = []
    for name in sorted(CONFIG_ALLOWLIST):
        fpath = agent_dir / name
        if fpath.exists() and fpath.is_file():
            stat = fpath.stat()
            results.append(
                {
                    "name": name,
                    "path": name,
                    "type": "file",
                    "size": stat.st_size,
                    "modified_at": stat.st_mtime,
                }
            )
    return results


@router.get("/workspace/{agent_id}/tree")
async def list_workspace_tree(
    agent_id: str,
    path: str = Query("", description="Subdirectory path relative to agent workspace"),
    recursive: bool = Query(False, description="List all files recursively"),
    auth: AuthContext = Depends(get_current_user),
):
    """List files and directories in an agent's workspace."""
    owner_id = resolve_owner_id(auth)
    workspace = get_workspace()

    agent_base = _agent_workspace_path(owner_id, agent_id)
    full_path = f"{agent_base}/{path}" if path else agent_base

    if recursive:
        all_entries: list = []
        _collect_recursive(workspace, owner_id, full_path, all_entries)
        return {"files": all_entries}
    else:
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


@router.get("/workspace/{agent_id}/config-files")
async def list_config_files(
    agent_id: str,
    auth: AuthContext = Depends(get_current_user),
):
    """List allowlisted agent config files (SOUL.md, MEMORY.md, etc.)."""
    owner_id = resolve_owner_id(auth)
    workspace = get_workspace()
    if "/" in agent_id or "\\" in agent_id or ".." in agent_id:
        raise HTTPException(status_code=400, detail="Invalid agent_id")
    return {"files": _list_config_files(workspace, owner_id, agent_id)}


@router.get("/workspace/{agent_id}/config-file")
async def read_config_file(
    agent_id: str,
    path: str = Query(..., description="Config filename (must be allowlisted)"),
    auth: AuthContext = Depends(get_current_user),
):
    """Read a single allowlisted agent config file."""
    owner_id = resolve_owner_id(auth)
    if path not in CONFIG_ALLOWLIST:
        raise HTTPException(status_code=400, detail=f"File not in allowlist: {path}")
    if "/" in agent_id or "\\" in agent_id or ".." in agent_id:
        raise HTTPException(status_code=400, detail="Invalid agent_id")
    workspace = get_workspace()
    full_path = f"agents/{agent_id}/{path}"
    try:
        info = workspace.read_file_info(owner_id, full_path)
    except WorkspaceError as exc:
        if "not found" in str(exc).lower():
            raise HTTPException(status_code=404, detail=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))
    return info


class WriteFileRequest(BaseModel):
    path: str
    content: str
    tab: str  # "workspace" or "config"


def _write_file(workspace, owner_id: str, agent_id: str, path: str, content: str, tab: str) -> str:
    """Write a file to workspace or config directory. Returns the written path."""
    if "/" in agent_id or "\\" in agent_id or ".." in agent_id:
        raise ValueError(f"Invalid agent_id: {agent_id!r}")

    if tab == "config":
        if path not in CONFIG_ALLOWLIST:
            raise ValueError(f"File not in allowlist: {path}")
        full_path = f"agents/{agent_id}/{path}"
    elif tab == "workspace":
        full_path = f"workspaces/{agent_id}/{path}"
    else:
        raise ValueError(f"Invalid tab: {tab!r}")

    workspace.write_file(owner_id, full_path, content)
    return full_path


@router.put("/workspace/{agent_id}/file")
async def write_workspace_file(
    agent_id: str,
    body: WriteFileRequest,
    auth: AuthContext = Depends(get_current_user),
):
    """Write a file to the agent's workspace or config directory."""
    owner_id = resolve_owner_id(auth)
    if "/" in agent_id or "\\" in agent_id or ".." in agent_id:
        raise HTTPException(status_code=400, detail="Invalid agent_id")
    if body.tab not in ("workspace", "config"):
        raise HTTPException(status_code=400, detail="tab must be 'workspace' or 'config'")

    workspace = get_workspace()
    try:
        written_path = _write_file(workspace, owner_id, agent_id, body.path, body.content, body.tab)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except WorkspaceError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    logger.info("Wrote %s for user %s (tab=%s)", written_path, owner_id, body.tab)
    return {"status": "ok", "path": written_path}
