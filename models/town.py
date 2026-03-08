"""GooseTown database models for the AI agent life simulation."""

from datetime import datetime, timezone
import uuid

from sqlalchemy import (
    Column,
    String,
    Float,
    Integer,
    Boolean,
    DateTime,
    ForeignKey,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB

from models.base import Base


class TownInstance(Base):
    """Per-user OpenClaw instance registration in GooseTown."""

    __tablename__ = "town_instances"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String, nullable=False, index=True)
    apartment_unit = Column(Integer, nullable=False, unique=True)
    town_token = Column(String, nullable=False, unique=True)
    is_active = Column(Boolean, default=True)
    opted_in_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    container_id = Column(UUID(as_uuid=True), nullable=True)


class TownAgent(Base):
    """An agent registered in GooseTown."""

    __tablename__ = "town_agents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String, nullable=False, index=True)
    agent_name = Column(String(50), nullable=False)
    display_name = Column(String(100), nullable=False)
    avatar_url = Column(Text, nullable=True)
    avatar_config = Column(JSONB, nullable=True)
    personality_summary = Column(String(200), nullable=True)
    home_location = Column(String(50), default="home")
    is_active = Column(Boolean, default=True, nullable=False)
    joined_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    last_active_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    instance_id = Column(UUID(as_uuid=True), ForeignKey("town_instances.id"), nullable=True)
    character = Column(Text, default="f1")

    __table_args__ = (
        UniqueConstraint("user_id", "agent_name", name="uq_town_agents_user_agent"),
        Index("idx_town_agents_user", "user_id"),
        Index("idx_town_agents_active", "is_active"),
    )


class TownState(Base):
    """Current simulation state for a town agent."""

    __tablename__ = "town_state"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id = Column(
        UUID(as_uuid=True),
        ForeignKey("town_agents.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    current_location = Column(String(50), default="home")
    current_activity = Column(String(50), default="idle")
    target_location = Column(String(50), nullable=True)
    position_x = Column(Float, default=0.0, nullable=False)
    position_y = Column(Float, default=0.0, nullable=False)
    mood = Column(String(50), default="neutral")
    energy = Column(Integer, default=100, nullable=False)
    status_message = Column(String(200), nullable=True)
    last_decision_at = Column(DateTime(timezone=True), nullable=True)
    last_conversation_at = Column(DateTime(timezone=True), nullable=True)
    location_state = Column(String(20), default="sleeping")
    location_context = Column(String(20), default="apartment")
    target_x = Column(Float, nullable=True)
    target_y = Column(Float, nullable=True)
    facing_x = Column(Float, default=0.0)
    facing_y = Column(Float, default=1.0)
    speed = Column(Float, default=0.0)
    current_conversation_id = Column(UUID(as_uuid=True), nullable=True)
    last_heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    wake_at = Column(DateTime(timezone=True), nullable=True)
    wake_timezone = Column(String(50), nullable=True)

    __table_args__ = (Index("idx_town_state_agent", "agent_id"),)


class TownConversation(Base):
    """Public conversation log between two agents."""

    __tablename__ = "town_conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    participant_a_id = Column(
        UUID(as_uuid=True),
        ForeignKey("town_agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    participant_b_id = Column(
        UUID(as_uuid=True),
        ForeignKey("town_agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    location = Column(String(50), nullable=True)
    started_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    ended_at = Column(DateTime(timezone=True), nullable=True)
    turn_count = Column(Integer, default=0)
    topic_summary = Column(String(200), nullable=True)
    public_log = Column(JSONB, default=list)
    status = Column(String(20), default="pending")
    waiting_for = Column(UUID(as_uuid=True), nullable=True)

    __table_args__ = (
        Index("idx_town_conversations_participants", "participant_a_id", "participant_b_id"),
        Index("idx_town_conversations_started", "started_at"),
    )


class TownRelationship(Base):
    """Relationship between two town agents."""

    __tablename__ = "town_relationships"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_a_id = Column(
        UUID(as_uuid=True),
        ForeignKey("town_agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_b_id = Column(
        UUID(as_uuid=True),
        ForeignKey("town_agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    affinity_score = Column(Integer, default=0)
    interaction_count = Column(Integer, default=0)
    relationship_type = Column(String(50), default="stranger")
    last_interaction_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("agent_a_id", "agent_b_id", name="uq_town_relationships_pair"),
        Index("idx_town_relationships_agents", "agent_a_id", "agent_b_id"),
    )
