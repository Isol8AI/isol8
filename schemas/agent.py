"""Pydantic schemas for agent API."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class CreateAgentRequest(BaseModel):
    """Request to create a new agent."""

    agent_name: str = Field(..., min_length=1, max_length=50, pattern="^[a-zA-Z0-9_-]+$")
    soul_content: Optional[str] = Field(None, max_length=10000)


class AgentResponse(BaseModel):
    """Agent details response."""

    agent_name: str
    user_id: str
    created_at: datetime
    updated_at: datetime
    soul_content: Optional[str] = None

    class Config:
        from_attributes = True


class AgentListResponse(BaseModel):
    """List of agents response."""

    agents: List[AgentResponse]
