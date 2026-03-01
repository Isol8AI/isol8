"""
Per-user OpenClaw container orchestration (ECS Fargate).

Each subscriber gets a dedicated ECS Service running an OpenClaw gateway
with a per-user EFS access point for data isolation. Agent workspaces
and openclaw.json configs live on EFS, and Cloud Map handles service
discovery for routing.
"""

import logging
from typing import Optional

from core.containers.ecs_manager import EcsManager, EcsManagerError
from core.containers.workspace import Workspace, WorkspaceError
from core.containers.http_client import GatewayHttpClient, GatewayRequestError

logger = logging.getLogger(__name__)

_ecs_manager: Optional[EcsManager] = None
_workspace: Optional[Workspace] = None


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


async def startup_containers() -> None:
    """No-op: ECS Services are always-on; no reconciliation needed at startup."""
    logger.info("Container startup: ECS services are always-on, nothing to reconcile")


async def shutdown_containers() -> None:
    """No-op: ECS Services keep running across control-plane restarts."""
    logger.info("Container shutdown: ECS services keep running")


__all__ = [
    "EcsManager",
    "EcsManagerError",
    "Workspace",
    "WorkspaceError",
    "GatewayHttpClient",
    "GatewayRequestError",
    "get_ecs_manager",
    "get_workspace",
    "startup_containers",
    "shutdown_containers",
]
