"""
Agent CRUD API endpoints.

All agent data is stored as plain files on disk. No encryption.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import get_current_user
from core.database import get_db
from core.gateway import get_gateway_manager
from core.services.agent_service import AgentService
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
    db: AsyncSession = Depends(get_db),
):
    service = AgentService(db)
    agents = await service.list_agents(auth.user_id)
    return AgentListResponse(
        agents=[
            AgentResponse(
                agent_name=a.agent_name,
                user_id=a.user_id,
                created_at=a.created_at,
                updated_at=a.updated_at,
                soul_content=a.soul_content,
            )
            for a in agents
        ]
    )


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
    db: AsyncSession = Depends(get_db),
):
    service = AgentService(db)

    # Check if agent already exists
    existing = await service.get_agent(auth.user_id, request.agent_name)
    if existing:
        raise HTTPException(status_code=409, detail=f"Agent '{request.agent_name}' already exists")

    # Create agent in DB
    agent = await service.create_agent(
        user_id=auth.user_id,
        agent_name=request.agent_name,
        soul_content=request.soul_content,
    )
    await db.commit()

    # Create workspace on disk
    gateway_manager = get_gateway_manager()
    gateway_manager.create_agent_workspace(
        agent_id=str(agent.id),
        soul_content=request.soul_content,
    )

    return AgentResponse(
        agent_name=agent.agent_name,
        user_id=agent.user_id,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
        soul_content=agent.soul_content,
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
    agent_name: str,
    auth=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = AgentService(db)
    agent = await service.get_agent(auth.user_id, agent_name)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")

    return AgentResponse(
        agent_name=agent.agent_name,
        user_id=agent.user_id,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
        soul_content=agent.soul_content,
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
    agent_name: str,
    auth=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = AgentService(db)

    # Get agent to find its UUID for workspace cleanup
    agent = await service.get_agent(auth.user_id, agent_name)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")

    agent_id = str(agent.id)

    # Delete from DB
    await service.delete_agent(auth.user_id, agent_name)
    await db.commit()

    # Delete workspace from disk
    gateway_manager = get_gateway_manager()
    gateway_manager.delete_agent_workspace(agent_id)
