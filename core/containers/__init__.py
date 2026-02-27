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

    Restarts containers that should be running based on DB records.
    Called from main.py lifespan handler.
    """
    manager = get_container_manager()
    try:
        manager.reconcile()
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
