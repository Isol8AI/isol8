"""
Per-user OpenClaw container orchestration.

Each user gets a dedicated Docker container running an OpenClaw
gateway instance.
"""

import logging
from typing import Optional

from core.containers.manager import ContainerManager, ContainerError
from core.containers.http_client import GatewayHttpClient, GatewayRequestError

logger = logging.getLogger(__name__)

_container_manager: Optional[ContainerManager] = None


def get_container_manager() -> ContainerManager:
    """Get the container manager singleton."""
    global _container_manager
    if _container_manager is None:
        from core.config import settings

        _container_manager = ContainerManager(
            containers_root=settings.CONTAINERS_ROOT,
            openclaw_image=settings.OPENCLAW_IMAGE,
            port_range_start=settings.CONTAINER_PORT_START,
            port_range_end=settings.CONTAINER_PORT_END,
        )
    return _container_manager


async def startup_containers() -> None:
    """Reconcile container state on application startup.

    Reads gateway tokens from the containers DB table and passes them
    to reconcile() so the in-memory cache has auth tokens for each
    running container.
    """
    from sqlalchemy import select
    from core.database import get_session_factory
    from models.container import Container

    # Read gateway tokens from DB
    db_tokens: dict[str, str] = {}
    try:
        session_factory = get_session_factory()
        async with session_factory() as db:
            result = await db.execute(
                select(Container.user_id, Container.gateway_token).where(Container.status == "running")
            )
            for row in result:
                if row.gateway_token:
                    db_tokens[row.user_id] = row.gateway_token
        logger.info("Loaded %d gateway tokens from DB", len(db_tokens))
    except Exception as e:
        logger.warning("Failed to load container tokens from DB: %s", e)

    manager = get_container_manager()
    try:
        manager.reconcile(db_tokens=db_tokens)
        logger.info("Container reconciliation complete")
    except Exception as e:
        logger.warning("Container reconciliation failed: %s", e)


async def shutdown_containers() -> None:
    """Clean up container manager on shutdown (containers keep running)."""
    global _container_manager
    _container_manager = None


__all__ = [
    "ContainerManager",
    "ContainerError",
    "GatewayHttpClient",
    "GatewayRequestError",
    "get_container_manager",
    "startup_containers",
    "shutdown_containers",
]
