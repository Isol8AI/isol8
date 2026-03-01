"""
Agent CRUD API endpoints.

EFS-backed: agent workspaces live on shared EFS at
{mount}/{user_id}/agents/{agent_name}/.
"""

import logging
import shutil

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field

from core.auth import get_current_user
from core.containers import get_workspace
from core.containers.workspace import WorkspaceError
from schemas.agent import AgentListResponse, AgentResponse, CreateAgentRequest

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "",
    response_model=AgentListResponse,
    summary="List agents",
    description="List all agents for the authenticated user.",
    operation_id="list_agents",
    responses={
        401: {"description": "Missing or invalid Clerk JWT token"},
    },
)
async def list_agents(
    auth=Depends(get_current_user),
):
    workspace = get_workspace()
    agent_names = workspace.list_agents(auth.user_id)
    return AgentListResponse(agents=[AgentResponse(agent_name=name) for name in agent_names])


@router.post(
    "",
    response_model=AgentResponse,
    status_code=201,
    summary="Create agent",
    description="Create a new agent with optional SOUL.md content.",
    operation_id="create_agent",
    responses={
        401: {"description": "Missing or invalid Clerk JWT token"},
        409: {"description": "Agent with this name already exists"},
    },
)
async def create_agent(
    request: CreateAgentRequest,
    auth=Depends(get_current_user),
):
    workspace = get_workspace()

    # Check if agent already exists
    existing_agents = workspace.list_agents(auth.user_id)
    if request.agent_name in existing_agents:
        raise HTTPException(status_code=409, detail=f"Agent '{request.agent_name}' already exists")

    # Ensure user directory exists and write SOUL.md
    workspace.ensure_user_dir(auth.user_id)
    soul_content = request.soul_content or ""
    workspace.write_file(auth.user_id, f"agents/{request.agent_name}/SOUL.md", soul_content)

    return AgentResponse(
        agent_name=request.agent_name,
        soul_content=soul_content if soul_content else None,
    )


@router.get(
    "/{agent_name}",
    response_model=AgentResponse,
    summary="Get agent",
    description="Get agent details by name.",
    operation_id="get_agent",
    responses={
        401: {"description": "Missing or invalid Clerk JWT token"},
        404: {"description": "Agent not found"},
    },
)
async def get_agent(
    agent_name: str = Path(..., min_length=1, max_length=50, pattern="^[a-zA-Z0-9_-]+$"),
    auth=Depends(get_current_user),
):
    workspace = get_workspace()

    # Check if agent exists
    existing_agents = workspace.list_agents(auth.user_id)
    if agent_name not in existing_agents:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")

    # Read SOUL.md if it exists
    soul_content = None
    try:
        soul_content = workspace.read_file(auth.user_id, f"agents/{agent_name}/SOUL.md")
    except WorkspaceError:
        pass  # SOUL.md may not exist, that's fine

    return AgentResponse(
        agent_name=agent_name,
        soul_content=soul_content,
    )


class UpdateAgentRequest(BaseModel):
    """Request to update an agent."""

    soul_content: Optional[str] = Field(None, max_length=10000)


@router.put(
    "/{agent_name}",
    response_model=AgentResponse,
    summary="Update agent",
    description="Update an agent's SOUL.md content.",
    operation_id="update_agent",
    responses={
        401: {"description": "Missing or invalid Clerk JWT token"},
        404: {"description": "Agent not found"},
    },
)
async def update_agent(
    request: UpdateAgentRequest,
    agent_name: str = Path(..., min_length=1, max_length=50, pattern="^[a-zA-Z0-9_-]+$"),
    auth=Depends(get_current_user),
):
    workspace = get_workspace()

    # Check if agent exists
    existing_agents = workspace.list_agents(auth.user_id)
    if agent_name not in existing_agents:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")

    # Write SOUL.md
    soul_content = request.soul_content or ""
    workspace.write_file(auth.user_id, f"agents/{agent_name}/SOUL.md", soul_content)

    return AgentResponse(
        agent_name=agent_name,
        soul_content=soul_content if soul_content else None,
    )


@router.delete(
    "/{agent_name}",
    status_code=204,
    summary="Delete agent",
    description="Delete an agent and its workspace.",
    operation_id="delete_agent",
    responses={
        401: {"description": "Missing or invalid Clerk JWT token"},
        404: {"description": "Agent not found"},
    },
)
async def delete_agent(
    agent_name: str = Path(..., min_length=1, max_length=50, pattern="^[a-zA-Z0-9_-]+$"),
    auth=Depends(get_current_user),
):
    workspace = get_workspace()

    # Check if agent exists
    existing_agents = workspace.list_agents(auth.user_id)
    if agent_name not in existing_agents:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")

    # Remove the entire agent directory from EFS (path-validated)
    try:
        agent_dir = workspace._resolve_user_file(auth.user_id, f"agents/{agent_name}")
        shutil.rmtree(agent_dir)
    except WorkspaceError as exc:
        logger.error("Path validation failed for agent %s: %s", agent_name, exc)
        raise HTTPException(status_code=400, detail="Invalid agent name") from exc
    except OSError as exc:
        logger.error("Failed to delete agent directory for %s: %s", agent_name, exc)
        raise HTTPException(status_code=500, detail="Failed to delete agent workspace") from exc
