"""
AgentState model for storing OpenClaw agent metadata.

Agent state lives as plain files on disk at the gateway workspace.
The database stores metadata only (name, soul content, timestamps).
"""

from datetime import datetime, timezone
import uuid

from sqlalchemy import (
    Column,
    String,
    Text,
    DateTime,
    UniqueConstraint,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID

from models.base import Base


class AgentState(Base):
    """
    Agent metadata storage.

    Agent files (sessions, memory) live on disk at the gateway workspace.
    The database tracks ownership and optional SOUL.md content.

    Attributes:
        id: Unique identifier (UUID) - primary key, used as workspace dir name
        user_id: Clerk user ID who owns this agent
        agent_name: User-chosen name for the agent (e.g., "luna", "rex")
        soul_content: Optional SOUL.md content (plaintext)
        created_at: When the agent was first created
        updated_at: When the agent was last updated
    """

    __tablename__ = "agent_states"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id = Column(String, nullable=False, index=True)
    agent_name = Column(String, nullable=False)

    # Optional SOUL.md content (personality/instructions)
    soul_content = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("user_id", "agent_name", name="uq_agent_states_user_agent"),
        Index("idx_agent_states_user", "user_id"),
    )

    def __repr__(self) -> str:
        return f"<AgentState(id={self.id}, user_id={self.user_id}, agent_name={self.agent_name})>"
