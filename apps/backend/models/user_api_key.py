"""Database model for user-provided API keys (BYOK)."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from models.base import Base


class UserApiKey(Base):
    """Stores user-provided API keys for external tools (BYOK)."""

    __tablename__ = "user_api_keys"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String, nullable=False)
    tool_id = Column(String, nullable=False)
    encrypted_key = Column(String, nullable=False)
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
        UniqueConstraint("user_id", "tool_id", name="uq_user_tool_key"),
        Index("idx_user_api_keys_user", "user_id"),
    )

    def __repr__(self) -> str:
        return f"<UserApiKey(user={self.user_id}, tool={self.tool_id})>"
