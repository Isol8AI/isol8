"""
Container model for tracking per-user OpenClaw ECS Fargate services.

Each subscriber gets a dedicated ECS Service with a unique service name
and a gateway auth token for API communication.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    String,
    Index,
    CheckConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

from models.base import Base


class Container(Base):
    """
    Per-user ECS Fargate service tracking.

    Maps a Clerk user ID to an ECS Service running an OpenClaw gateway
    task discovered via Cloud Map.

    Attributes:
        id: Unique identifier (UUID).
        user_id: Clerk user ID (unique -- one service per user).
        service_name: ECS service name (set after creation).
        task_arn: Current ECS task ARN (updated on deployment).
        gateway_token: Auth token for the OpenClaw gateway HTTP API.
        status: Service lifecycle state.
        created_at: When the service was first provisioned.
        updated_at: Last status change.
    """

    __tablename__ = "containers"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id = Column(String, nullable=False, unique=True, index=True)

    # ECS Fargate fields
    service_name = Column(String, unique=True, nullable=True)
    task_arn = Column(String, nullable=True)

    # Auth
    gateway_token = Column(String, nullable=False)

    # Status: provisioning, running, stopped, error
    status = Column(
        String,
        nullable=False,
        default="stopped",
        server_default="stopped",
    )

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
        CheckConstraint(
            "status IN ('provisioning', 'running', 'stopped', 'error')",
            name="chk_container_status",
        ),
        Index("idx_containers_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<Container(user_id={self.user_id}, service_name={self.service_name}, status={self.status})>"
