"""
Node connection proxy.

Manages dedicated upstream WebSocket connections for node clients.
When a node connects (role:"node" in the connect handshake), a separate
upstream WebSocket is opened to the user's container. All subsequent
messages are relayed bidirectionally. The container config is patched
to enable/disable node tools on connect/disconnect.
"""

import logging

from core.gateway.node_connection import NodeUpstreamConnection
from core.containers import get_ecs_manager, get_gateway_pool
from core.config import settings
from core.services.config_patcher import patch_openclaw_config

logger = logging.getLogger(__name__)

# connectionId -> NodeUpstreamConnection
_node_upstreams: dict[str, NodeUpstreamConnection] = {}


async def handle_node_connect(
    owner_id: str,
    connection_id: str,
    connect_params: dict,
    management_api,
) -> dict | None:
    """
    Open a dedicated upstream to the container, complete the node handshake,
    and set up bidirectional relay. Returns the hello-ok dict on success.
    """
    ecs = get_ecs_manager()
    container, ip = await ecs.resolve_running_container(owner_id)

    upstream = NodeUpstreamConnection(
        user_id=owner_id,
        container_ip=ip,
        node_connect_params=connect_params,
        efs_mount_path=settings.EFS_MOUNT_PATH,
    )

    async def on_upstream_message(data: dict):
        await management_api.send_message(connection_id, data)

    upstream.set_message_callback(on_upstream_message)

    hello = await upstream.connect()
    await upstream.start_reader()

    _node_upstreams[connection_id] = upstream

    # Enable node tools in container config (remove "nodes" from deny list)
    await patch_openclaw_config(owner_id, {"tools": {"deny": ["canvas"]}})

    # Broadcast status to chat connections
    pool = get_gateway_pool()
    await pool.broadcast_to_user(owner_id, {"type": "node_status", "status": "connected"})

    logger.info("Node proxy established: user=%s conn=%s", owner_id, connection_id)
    return hello


async def handle_node_message(connection_id: str, message: dict) -> None:
    """Relay a message from the node client to the upstream container."""
    upstream = _node_upstreams.get(connection_id)
    if upstream:
        await upstream.relay_to_upstream(message)
    else:
        logger.warning("No node upstream for connection %s", connection_id)


async def handle_node_disconnect(connection_id: str, owner_id: str) -> None:
    """Close the upstream connection and re-disable node tools."""
    upstream = _node_upstreams.pop(connection_id, None)
    if upstream:
        await upstream.close()

    # Re-disable node tools
    await patch_openclaw_config(owner_id, {"tools": {"deny": ["canvas", "nodes"]}})

    # Broadcast status
    pool = get_gateway_pool()
    await pool.broadcast_to_user(owner_id, {"type": "node_status", "status": "disconnected"})

    logger.info("Node proxy closed: conn=%s", connection_id)


def is_node_connection(connection_id: str) -> bool:
    """Check if a connection ID has a registered node upstream."""
    return connection_id in _node_upstreams
