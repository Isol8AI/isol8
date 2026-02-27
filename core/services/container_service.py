"""
Service for managing container records in the database.

The DB is the source of truth for which users have containers and
their port assignments. The ContainerManager (Docker) is the runtime.
"""

import logging
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.container import Container

logger = logging.getLogger(__name__)


class ContainerService:
    """Service for container DB operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_container(self, user_id: str) -> Optional[Container]:
        """Get a user's container record."""
        result = await self.db.execute(select(Container).where(Container.user_id == user_id))
        return result.scalar_one_or_none()

    async def create_container(
        self,
        user_id: str,
        port: int,
        container_id: Optional[str] = None,
        status: str = "provisioning",
    ) -> Container:
        """Create a container record."""
        container = Container(
            user_id=user_id,
            port=port,
            container_id=container_id,
            status=status,
        )
        self.db.add(container)
        await self.db.flush()
        logger.info("Created container record: user=%s port=%d", user_id, port)
        return container

    async def update_status(
        self,
        user_id: str,
        status: str,
        container_id: Optional[str] = None,
    ) -> Optional[Container]:
        """Update a container's status and optionally its Docker ID."""
        container = await self.get_container(user_id)
        if not container:
            return None

        container.status = status
        if container_id is not None:
            container.container_id = container_id
        await self.db.flush()
        logger.info("Updated container status: user=%s status=%s", user_id, status)
        return container

    async def delete_container(self, user_id: str) -> bool:
        """Delete a container record."""
        container = await self.get_container(user_id)
        if not container:
            return False

        await self.db.delete(container)
        await self.db.flush()
        logger.info("Deleted container record: user=%s", user_id)
        return True

    async def list_containers(self, status: Optional[str] = None) -> List[Container]:
        """List all container records, optionally filtered by status."""
        query = select(Container)
        if status:
            query = query.where(Container.status == status)
        query = query.order_by(Container.created_at.desc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_next_available_port(
        self,
        port_start: int = 19000,
        port_end: int = 19999,
    ) -> int:
        """Find the next available port not assigned to any container."""
        result = await self.db.execute(select(Container.port).order_by(Container.port))
        used_ports = {row[0] for row in result.all()}

        for port in range(port_start, port_end + 1):
            if port not in used_ports:
                return port

        raise ValueError(f"No available ports in range {port_start}-{port_end}")
