"""
Per-user OpenClaw container orchestration (ECS Fargate).

Each subscriber gets a dedicated ECS Service running an OpenClaw gateway.
Agent workspaces live on EFS, openclaw.json configs live in S3, and
Cloud Map handles service discovery for routing.
"""

import logging
from typing import Optional

from core.containers.ecs_manager import EcsManager, EcsManagerError
from core.containers.config_store import ConfigStore, ConfigStoreError
from core.containers.workspace import Workspace, WorkspaceError
from core.containers.http_client import GatewayHttpClient, GatewayRequestError

logger = logging.getLogger(__name__)

_ecs_manager: Optional[EcsManager] = None
_config_store: Optional[ConfigStore] = None
_workspace: Optional[Workspace] = None


def get_ecs_manager() -> EcsManager:
    """Get the ECS manager singleton."""
    global _ecs_manager
    if _ecs_manager is None:
        _ecs_manager = EcsManager()
    return _ecs_manager


def get_config_store() -> ConfigStore:
    """Get the S3 config store singleton."""
    global _config_store
    if _config_store is None:
        from core.config import settings

        _config_store = ConfigStore(bucket=settings.S3_CONFIG_BUCKET)
    return _config_store


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
    "ConfigStore",
    "ConfigStoreError",
    "Workspace",
    "WorkspaceError",
    "GatewayHttpClient",
    "GatewayRequestError",
    "get_ecs_manager",
    "get_config_store",
    "get_workspace",
    "startup_containers",
    "shutdown_containers",
]
