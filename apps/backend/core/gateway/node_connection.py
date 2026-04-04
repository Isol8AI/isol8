"""
Dedicated per-user upstream WebSocket for node connections.

The OpenClaw gateway enforces one-role-per-connection, so node traffic
cannot share the operator connection used by GatewayConnectionPool.
This class manages a separate WebSocket to the container that connects
with role:"node", enabling the gateway's NodeRegistry to register the
node and route node.invoke requests to the user's Mac.
"""

import asyncio
import base64
import hashlib
import json
import logging
import time
import uuid

from websockets import connect as ws_connect

logger = logging.getLogger(__name__)

GATEWAY_PORT = 18789


def _base64url_encode(data: bytes) -> str:
    """RFC 7515 base64url encoding (no padding)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _build_device_identity(nonce: str, connect_params: dict) -> dict:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    """Generate an Ed25519 device identity block for the connect handshake.

    OpenClaw v2 signing format (pipe-delimited):
      v2|{deviceId}|{clientId}|{clientMode}|{role}|{scopes}|{signedAtMs}|{token}|{nonce}

    The keypair is ephemeral — trusted-proxy auth handles user identity, this
    just needs to be cryptographically consistent.
    """
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    raw_pub = public_key.public_bytes_raw()

    device_id = hashlib.sha256(raw_pub).hexdigest()
    signed_at = int(time.time() * 1000)

    client = connect_params.get("client", {})
    client_id = client.get("id", "gateway-client")
    client_mode = client.get("mode", "node")
    role = connect_params.get("role", "node")
    scopes = ",".join(sorted(connect_params.get("scopes", [])))
    token = connect_params.get("auth", {}).get("token", "")

    # v2 pipe-delimited signing payload
    payload = f"v2|{device_id}|{client_id}|{client_mode}|{role}|{scopes}|{signed_at}|{token}|{nonce}"
    signature = private_key.sign(payload.encode("utf-8"))

    return {
        "id": device_id,
        "publicKey": _base64url_encode(raw_pub),
        "signature": _base64url_encode(signature),
        "signedAt": signed_at,
        "nonce": nonce,
    }


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

        # Step 2: build device identity from challenge nonce
        # Nonce may be at top level or inside payload
        payload = challenge.get("payload", challenge)
        nonce = payload.get("nonce", challenge.get("nonce", ""))
        device = _build_device_identity(nonce, self.node_connect_params)

        # Step 3: send connect with role:node + device identity
        req_id = str(uuid.uuid4())
        connect_msg = {
            "type": "req",
            "id": req_id,
            "method": "connect",
            "params": {
                "minProtocol": 3,
                "maxProtocol": 3,
                **self.node_connect_params,
                "device": device,
            },
        }
        await self._ws.send(json.dumps(connect_msg))

        # Step 4: receive hello-ok
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
