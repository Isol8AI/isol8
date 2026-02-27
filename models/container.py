"""
Container model for tracking per-user OpenClaw Docker containers.

Each paying user gets a dedicated container with a unique port mapping.
Free-tier users have no container record and use the shared gateway.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    String,
    Index,
    CheckConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

from models.base import Base


class Container(Base):
    """
    Per-user Docker container tracking.

    Maps a Clerk user ID to a running Docker container with a unique
    host port for the OpenClaw gateway.

    Attributes:
        id: Unique identifier (UUID).
        user_id: Clerk user ID (unique — one container per user).
        port: Host port mapped to the container's gateway (19000-19999).
        container_id: Docker container ID (set after provisioning).
        status: Container lifecycle state.
        created_at: When the container was first provisioned.
        updated_at: Last status change.
    """

    __tablename__ = "containers"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id = Column(String, nullable=False, unique=True)
    port = Column(Integer, nullable=False, unique=True)
    container_id = Column(String, nullable=True)
    status = Column(
        String,
        nullable=False,
        default="provisioning",
        server_default="provisioning",
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
        CheckConstraint(
            "port >= 19000 AND port <= 19999",
            name="chk_container_port_range",
        ),
        Index("idx_containers_user", "user_id", unique=True),
        Index("idx_containers_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<Container(user_id={self.user_id}, port={self.port}, status={self.status})>"
