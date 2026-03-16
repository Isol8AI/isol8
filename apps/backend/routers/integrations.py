"""MCP server integration management endpoints.

CRUD for mcporter config (MCP server definitions) stored on the user's
EFS workspace at .mcporter/mcporter.json.
"""

import json
import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.auth import AuthContext, get_current_user
from core.containers import get_workspace
from core.containers.workspace import WorkspaceError

logger = logging.getLogger(__name__)

router = APIRouter()

MCPORTER_CONFIG_PATH = ".mcporter/mcporter.json"


class ServerEntry(BaseModel):
    command: str = Field(..., description="Command to run the MCP server")
    args: list[str] = Field(default_factory=list, description="Command arguments")
    env: Dict[str, str] = Field(default_factory=dict, description="Environment variables")


class ServersResponse(BaseModel):
    servers: Dict[str, Any]


class PutServersRequest(BaseModel):
    servers: Dict[str, Any] = Field(..., description="Complete servers dict to replace")


class PatchServerRequest(BaseModel):
    command: str = Field(..., description="Command to run the MCP server")
    args: list[str] = Field(default_factory=list, description="Command arguments")
    env: Dict[str, str] = Field(default_factory=dict, description="Environment variables")


def _read_mcporter_config(user_id: str) -> dict:
    """Read and parse the user's mcporter.json, returning empty servers if missing."""
    workspace = get_workspace()
    try:
        raw = workspace.read_file(user_id, MCPORTER_CONFIG_PATH)
        return json.loads(raw)
    except WorkspaceError:
        return {"servers": {}}
    except json.JSONDecodeError:
        logger.warning("Corrupt mcporter.json for user %s, resetting", user_id)
        return {"servers": {}}


def _write_mcporter_config(user_id: str, config: dict) -> None:
    """Write the user's mcporter.json."""
    workspace = get_workspace()
    workspace.write_file(user_id, MCPORTER_CONFIG_PATH, json.dumps(config, indent=2))


def _validate_servers(servers: dict) -> None:
    """Validate that each server entry has at minimum a command field (string)."""
    for name, entry in servers.items():
        if not isinstance(entry, dict):
            raise HTTPException(
                status_code=422,
                detail=f"Server '{name}' must be an object",
            )
        if "command" not in entry or not isinstance(entry["command"], str):
            raise HTTPException(
                status_code=422,
                detail=f"Server '{name}' must have a 'command' string field",
            )


@router.get(
    "/integrations/mcp/servers",
    summary="List configured MCP servers",
    description="Returns all MCP server entries from the user's mcporter.json config.",
    response_model=ServersResponse,
    operation_id="list_mcp_servers",
    tags=["integrations"],
)
async def list_mcp_servers(
    auth: AuthContext = Depends(get_current_user),
):
    config = _read_mcporter_config(auth.user_id)
    return {"servers": config.get("servers", {})}


@router.put(
    "/integrations/mcp/servers",
    summary="Replace all MCP server configurations",
    description="Replaces the entire servers dict in the user's mcporter.json config.",
    response_model=ServersResponse,
    operation_id="replace_mcp_servers",
    tags=["integrations"],
)
async def replace_mcp_servers(
    body: PutServersRequest,
    auth: AuthContext = Depends(get_current_user),
):
    _validate_servers(body.servers)
    config = _read_mcporter_config(auth.user_id)
    config["servers"] = body.servers
    _write_mcporter_config(auth.user_id, config)
    return {"servers": config["servers"]}


@router.patch(
    "/integrations/mcp/servers/{name}",
    summary="Add or update a single MCP server",
    description="Adds or updates a single MCP server entry by name.",
    response_model=ServersResponse,
    operation_id="upsert_mcp_server",
    tags=["integrations"],
)
async def upsert_mcp_server(
    name: str,
    body: PatchServerRequest,
    auth: AuthContext = Depends(get_current_user),
):
    config = _read_mcporter_config(auth.user_id)
    servers = config.get("servers", {})
    servers[name] = body.model_dump()
    config["servers"] = servers
    _write_mcporter_config(auth.user_id, config)
    return {"servers": config["servers"]}


@router.delete(
    "/integrations/mcp/servers/{name}",
    summary="Remove an MCP server",
    description="Removes an MCP server entry by name.",
    response_model=ServersResponse,
    operation_id="delete_mcp_server",
    tags=["integrations"],
)
async def delete_mcp_server(
    name: str,
    auth: AuthContext = Depends(get_current_user),
):
    config = _read_mcporter_config(auth.user_id)
    servers = config.get("servers", {})
    servers.pop(name, None)
    config["servers"] = servers
    _write_mcporter_config(auth.user_id, config)
    return {"servers": config["servers"]}
