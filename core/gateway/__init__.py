"""
OpenClaw Gateway module.

Manages the persistent OpenClaw gateway process on EC2.
Agent state lives as plain files on disk at GATEWAY_WORKSPACE.
"""

import logging
from typing import Optional

from core.gateway.manager import GatewayManager, GatewayUnavailableError
from core.gateway.http_client import GatewayHttpClient, GatewayRequestError

logger = logging.getLogger(__name__)

_gateway_manager: Optional[GatewayManager] = None
_gateway_client: Optional[GatewayHttpClient] = None


def get_gateway_manager() -> GatewayManager:
    """Get the gateway manager singleton."""
    global _gateway_manager
    if _gateway_manager is None:
        from core.config import settings

        _gateway_manager = GatewayManager(
            port=settings.GATEWAY_PORT,
            workspace=settings.GATEWAY_WORKSPACE,
        )
    return _gateway_manager


def get_gateway_client() -> GatewayHttpClient:
    """Get the gateway HTTP client singleton."""
    global _gateway_client
    if _gateway_client is None:
        manager = get_gateway_manager()
        _gateway_client = GatewayHttpClient(base_url=manager.base_url)
    return _gateway_client


async def startup_gateway() -> None:
    """Start the OpenClaw gateway on application startup."""
    import os

    manager = get_gateway_manager()
    env = {
        "AWS_REGION": os.environ.get("AWS_REGION", "us-east-1"),
        "AWS_DEFAULT_REGION": os.environ.get("AWS_DEFAULT_REGION", os.environ.get("AWS_REGION", "us-east-1")),
        "BRAVE_API_KEY": os.environ.get("BRAVE_API_KEY", ""),
    }

    # Pass through IAM role credentials if present (EC2 instance profile)
    for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        val = os.environ.get(key)
        if val:
            env[key] = val

    try:
        manager.start(env)
        logger.info("OpenClaw gateway started on port %d", manager.port)
    except GatewayUnavailableError:
        logger.warning("OpenClaw gateway failed to start — agent chat will be unavailable")


async def shutdown_gateway() -> None:
    """Stop the OpenClaw gateway on application shutdown."""
    global _gateway_manager, _gateway_client
    if _gateway_manager is not None:
        _gateway_manager.stop()
        logger.info("OpenClaw gateway stopped")
    _gateway_manager = None
    _gateway_client = None


__all__ = [
    "GatewayManager",
    "GatewayUnavailableError",
    "GatewayHttpClient",
    "GatewayRequestError",
    "get_gateway_manager",
    "get_gateway_client",
    "startup_gateway",
    "shutdown_gateway",
]
