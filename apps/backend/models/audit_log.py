"""
Audit log model for security-relevant events.

Security Note:
- Logs are append-only (never updated or deleted in normal operation)
- Contains NO encrypted content or keys - only metadata
- Used for compliance, debugging, and security monitoring
"""

from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional, Dict, Any

from sqlalchemy import Column, String, DateTime, ForeignKey, Index, Enum, JSON
from sqlalchemy.orm import relationship

from .base import Base


class AuditEventType(str, PyEnum):
    """Types of security-relevant events."""

    # Authentication events (from Clerk webhooks)
    USER_SIGNED_IN = "user_signed_in"
    USER_SIGNED_OUT = "user_signed_out"

    # Agent events
    AGENT_CREATED = "agent_created"
    AGENT_DELETED = "agent_deleted"


class AuditLog(Base):
    """
    Immutable audit log for security events.

    Every security-relevant action is logged here for:
    - Compliance requirements
    - Security incident investigation
    - Debugging

    Fields:
        event_type: What happened
        actor_user_id: Who did it
        target_user_id: Who was affected (if applicable)
        event_data: Additional context (JSON)
    """

    __tablename__ = "audit_logs"

    id = Column(String, primary_key=True)  # UUID

    # Event type
    event_type = Column(Enum(AuditEventType), nullable=False)

    # Actor - who performed the action
    actor_user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Target - who was affected
    target_user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Additional event details (flexible JSON)
    event_data = Column(JSON, nullable=True)

    # Timestamp (never modified)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    actor = relationship("User", foreign_keys=[actor_user_id])
    target = relationship("User", foreign_keys=[target_user_id])

    # Indexes
    __table_args__ = (
        Index("ix_audit_logs_event_type", "event_type"),
        Index("ix_audit_logs_actor", "actor_user_id"),
        Index("ix_audit_logs_target", "target_user_id"),
        Index("ix_audit_logs_created_at", "created_at"),
        Index("ix_audit_logs_event_created", "event_type", "created_at"),
    )

    @classmethod
    def create(
        cls,
        id: str,
        event_type: AuditEventType,
        actor_user_id: Optional[str] = None,
        target_user_id: Optional[str] = None,
        event_data: Optional[Dict[str, Any]] = None,
    ) -> "AuditLog":
        """Create an audit log entry."""
        return cls(
            id=id,
            event_type=event_type,
            actor_user_id=actor_user_id,
            target_user_id=target_user_id,
            event_data=event_data,
        )

    def to_api_response(self) -> dict:
        """Convert to API response format."""
        return {
            "id": self.id,
            "event_type": self.event_type.value,
            "actor_user_id": self.actor_user_id,
            "target_user_id": self.target_user_id,
            "event_data": self.event_data,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
