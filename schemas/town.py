"""Pydantic schemas for GooseTown API."""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class TownOptInRequest(BaseModel):
    """Request to register an agent in GooseTown."""

    agent_name: str = Field(..., min_length=1, max_length=50, pattern="^[a-zA-Z0-9_-]+$")
    display_name: str = Field(..., min_length=1, max_length=100)
    personality_summary: Optional[str] = Field(None, max_length=200)
    avatar_config: Optional[dict] = None


class TownOptOutRequest(BaseModel):
    """Request to remove an agent from GooseTown."""

    agent_name: str = Field(..., min_length=1, max_length=50, pattern="^[a-zA-Z0-9_-]+$")


class TownAgentResponse(BaseModel):
    """Public info about a town agent."""

    id: UUID
    user_id: str
    agent_name: str
    display_name: str
    avatar_url: Optional[str] = None
    avatar_config: Optional[dict] = None
    personality_summary: Optional[str] = None
    home_location: Optional[str] = None
    is_active: bool
    joined_at: datetime

    class Config:
        from_attributes = True


class TownAgentStateResponse(BaseModel):
    """Current state of a town agent (position, activity, mood)."""

    agent_id: UUID
    display_name: str
    current_location: Optional[str] = None
    current_activity: Optional[str] = None
    target_location: Optional[str] = None
    position_x: float
    position_y: float
    mood: Optional[str] = None
    energy: int
    status_message: Optional[str] = None


class TownStateResponse(BaseModel):
    """Full town state snapshot."""

    agents: List[TownAgentStateResponse]
    timestamp: datetime


class ConversationTurn(BaseModel):
    """A single turn in a conversation."""

    speaker: str
    text: str


class TownConversationResponse(BaseModel):
    """Public conversation log."""

    id: UUID
    participant_a: str
    participant_b: str
    location: Optional[str] = None
    started_at: datetime
    ended_at: Optional[datetime] = None
    turn_count: int
    topic_summary: Optional[str] = None
    public_log: List[ConversationTurn]

    class Config:
        from_attributes = True


class TownConversationsListResponse(BaseModel):
    """List of recent conversations."""

    conversations: List[TownConversationResponse]


# ---------------------------------------------------------------------------
# Instance-based opt-in/opt-out schemas
# ---------------------------------------------------------------------------


class TownAgentOptIn(BaseModel):
    """Single agent within an instance opt-in request."""

    agent_name: str = Field(..., min_length=1, max_length=50, pattern="^[a-zA-Z0-9_-]+$")
    display_name: str = Field(..., min_length=1, max_length=100)
    personality_summary: Optional[str] = Field(None, max_length=200)


class TownInstanceOptInRequest(BaseModel):
    """Request to register a user instance with one or more agents."""

    agents: List[TownAgentOptIn] = Field(..., min_length=1)


class TownInstanceOptInAgentResponse(BaseModel):
    """Agent info in the instance opt-in response."""

    agent_name: str
    display_name: str
    personality_summary: Optional[str] = None
    is_active: bool


class TownInstanceOptInResponse(BaseModel):
    """Response after successful instance opt-in."""

    instance_id: UUID
    apartment_unit: int
    town_token: str
    agents: List[TownInstanceOptInAgentResponse]


class TownInstanceOptOutResponse(BaseModel):
    """Response after successful instance opt-out."""

    status: str
    deactivated_agents: int


class ApartmentAgentState(BaseModel):
    """Agent state for the apartment view."""

    agent_id: UUID
    agent_name: str
    display_name: str
    character: Optional[str] = None
    current_location: Optional[str] = None
    current_activity: Optional[str] = None
    mood: Optional[str] = None
    energy: int = 100
    status_message: Optional[str] = None
    position_x: float = 0.0
    position_y: float = 0.0
    is_active: bool = True


class ApartmentActivityEvent(BaseModel):
    """Activity event in the apartment feed."""

    agent_name: str
    display_name: str
    event_type: str
    description: str
    location: Optional[str] = None
    timestamp: datetime


class ApartmentResponse(BaseModel):
    """Full apartment view response."""

    agents: List[ApartmentAgentState]
    activity: List[ApartmentActivityEvent]
