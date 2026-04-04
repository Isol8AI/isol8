"""
Dedicated per-user upstream WebSocket for node connections.

The OpenClaw gateway enforces one-role-per-connection, so node traffic
cannot share the operator connection used by GatewayConnectionPool.
This class manages a separate WebSocket to the container that connects
with role:"node", enabling the gateway's NodeRegistry to register the
node and route node.invoke requests to the user's Mac.
"""

import asyncio
import json
import logging
import uuid

from websockets import connect as ws_connect

logger = logging.getLogger(__name__)

GATEWAY_PORT = 18789


class NodeUpstreamConnection:
    """Manages a single upstream WebSocket connection for a node."""

    def __init__(
        self,
        user_id: str,
        container_ip: str,
        node_connect_params: dict,
    ):
        self.user_id = user_id
        self.container_ip = container_ip
        self.node_connect_params = node_connect_params
        self._ws = None
        self._connected = False
        self._reader_task: asyncio.Task | None = None
        self._on_message = None

    async def connect(self) -> dict:
        """Open upstream WS, complete handshake with role:node. Returns hello-ok."""
        uri = f"ws://{self.container_ip}:{GATEWAY_PORT}"
        self._ws = await ws_connect(
            uri,
            open_timeout=10,
            close_timeout=5,
            additional_headers={"x-forwarded-user": self.user_id},
        )

        # Step 1: receive connect.challenge
        raw = await asyncio.wait_for(self._ws.recv(), timeout=10)
        challenge = json.loads(raw)
        if challenge.get("event") != "connect.challenge":
            raise RuntimeError(f"Expected connect.challenge, got {challenge}")

        # Step 2: send connect with role:node
        req_id = str(uuid.uuid4())
        connect_msg = {
            "type": "req",
            "id": req_id,
            "method": "connect",
            "params": {
                "minProtocol": 3,
                "maxProtocol": 3,
                **self.node_connect_params,
            },
        }
        await self._ws.send(json.dumps(connect_msg))

        # Step 3: receive hello-ok
        raw = await asyncio.wait_for(self._ws.recv(), timeout=10)
        resp = json.loads(raw)
        if not resp.get("ok"):
            error = resp.get("error", {}).get("message", "unknown")
            raise RuntimeError(f"Node handshake failed: {error}")

        self._connected = True
        logger.info("Node upstream connected for user %s", self.user_id)
        return resp

    def set_message_callback(self, callback) -> None:
        """Set callback for messages from upstream (container -> node)."""
        self._on_message = callback

    async def start_reader(self) -> None:
        """Start reading from upstream and forwarding to callback."""
        self._reader_task = asyncio.create_task(self._reader_loop())

    async def _reader_loop(self) -> None:
        try:
            async for raw in self._ws:
                if self._on_message:
                    data = json.loads(raw)
                    await self._on_message(data)
        except Exception as e:
            logger.warning("Node upstream reader error for %s: %s", self.user_id, e)
        finally:
            self._connected = False

    async def relay_to_upstream(self, message: dict) -> None:
        """Forward a message from the node client to the container."""
        if self._ws and self._connected:
            await self._ws.send(json.dumps(message))

    async def close(self) -> None:
        self._connected = False
        if self._reader_task:
            self._reader_task.cancel()
        if self._ws:
            await self._ws.close()
        logger.info("Node upstream closed for user %s", self.user_id)
