"""
Per-user OpenClaw container orchestration (ECS Fargate).

Each subscriber gets a dedicated ECS Service running an OpenClaw gateway
with a per-user EFS access point for data isolation. Agent workspaces
and openclaw.json configs live on EFS, and Cloud Map handles service
discovery for routing.
"""

import logging
from typing import Any, Optional

from core.containers.ecs_manager import EcsManager, EcsManagerError
from core.containers.workspace import Workspace, WorkspaceError
from core.containers.http_client import GatewayHttpClient, GatewayRequestError

# GatewayConnectionPool is imported lazily in get_gateway_pool() to avoid
# circular import: connection_pool → core.containers.ecs_manager → this __init__

logger = logging.getLogger(__name__)

_ecs_manager: Optional[EcsManager] = None
_workspace: Optional[Workspace] = None
_gateway_pool = None  # type: Optional[Any]  -- lazy import avoids circular dep


def get_ecs_manager() -> EcsManager:
    """Get the ECS manager singleton."""
    global _ecs_manager
    if _ecs_manager is None:
        _ecs_manager = EcsManager()
    return _ecs_manager


def get_workspace() -> Workspace:
    """Get the EFS workspace singleton."""
    global _workspace
    if _workspace is None:
        from core.config import settings

        _workspace = Workspace(mount_path=settings.EFS_MOUNT_PATH)
    return _workspace


def get_gateway_pool() -> Any:
    """Get the gateway connection pool singleton (GatewayConnectionPool)."""
    global _gateway_pool
    if _gateway_pool is None:
        from core.gateway.connection_pool import GatewayConnectionPool
        from core.services.management_api_client import ManagementApiClient

        _gateway_pool = GatewayConnectionPool(
            management_api=ManagementApiClient(),
        )
    return _gateway_pool


async def startup_containers() -> None:
    """No-op: ECS Services are always-on; no reconciliation needed at startup."""
    logger.info("Container startup: ECS services are always-on, nothing to reconcile")


async def shutdown_containers() -> None:
    """Close gateway connection pool; ECS Services keep running."""
    global _gateway_pool
    if _gateway_pool is not None:
        await _gateway_pool.close_all()
        _gateway_pool = None
    logger.info("Container shutdown complete")


__all__ = [
    "EcsManager",
    "EcsManagerError",
    "Workspace",
    "WorkspaceError",
    "GatewayHttpClient",
    "GatewayRequestError",
    "GatewayConnectionPool",
    "get_ecs_manager",
    "get_gateway_pool",
    "get_workspace",
    "startup_containers",
    "shutdown_containers",
]
