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

NODE_KEY_PATH = "devices/.node-device-key.pem"


def _base64url_encode(data: bytes) -> str:
    """RFC 7515 base64url encoding (no padding)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _load_private_key(pem: str):
    """Load an Ed25519 private key from PEM string."""
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    return load_pem_private_key(pem.encode("ascii"), password=None)


def _build_device_identity(private_key, nonce: str, connect_params: dict) -> dict:
    """Build a signed device identity block for the connect handshake.

    Uses the v2 pipe-delimited signing format:
      v2|{deviceId}|{clientId}|{clientMode}|{role}|{scopes}|{signedAtMs}|{token}|{nonce}
    """
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    raw_pub = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    device_id = hashlib.sha256(raw_pub).hexdigest()
    signed_at = int(time.time() * 1000)

    client = connect_params.get("client", {})
    client_id = client.get("id", "gateway-client")
    client_mode = client.get("mode", "node")
    role = connect_params.get("role", "node")
    scopes = ",".join(sorted(connect_params.get("scopes", [])))
    token = connect_params.get("auth", {}).get("token", "")

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
        efs_mount_path: str,
        gateway_token: str,
    ):
        self.user_id = user_id
        self.container_ip = container_ip
        self.node_connect_params = node_connect_params
        self.efs_mount_path = efs_mount_path
        self.gateway_token = gateway_token
        self._ws = None
        self._connected = False
        self._reader_task: asyncio.Task | None = None
        self._on_message = None

    def _load_node_key(self):
        """Read the persistent Ed25519 private key from EFS."""
        import pathlib

        key_path = pathlib.Path(self.efs_mount_path) / self.user_id / NODE_KEY_PATH
        if not key_path.exists():
            raise RuntimeError(f"Node device key not found at {key_path}. Re-provision the container to generate it.")
        pem = key_path.read_text(encoding="ascii")
        return _load_private_key(pem)

    async def connect(self) -> dict:
        """Open upstream WS, complete handshake with role:node. Returns hello-ok."""
        # Load persistent device key
        private_key = self._load_node_key()
        logger.info("Loaded node device key for user %s", self.user_id)

        uri = f"ws://{self.container_ip}:{GATEWAY_PORT}"
        self._ws = await ws_connect(
            uri,
            open_timeout=10,
            close_timeout=5,
        )

        # Step 1: receive connect.challenge
        raw = await asyncio.wait_for(self._ws.recv(), timeout=10)
        challenge = json.loads(raw)
        if challenge.get("event") != "connect.challenge":
            raise RuntimeError(f"Expected connect.challenge, got {challenge}")

        # Step 2: extract nonce and sign with persistent device key
        payload = challenge.get("payload", challenge)
        nonce = payload.get("nonce", challenge.get("nonce", ""))
        device = _build_device_identity(private_key, nonce, self.node_connect_params)

        # Step 3: send connect with role:node + device identity + token auth.
        # Nodes always require device identity (OpenClaw doesn't allow nodes
        # to skip via shared auth), but token auth still needs to pass for the
        # primary auth check in token mode.
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
                "auth": {"token": self.gateway_token},
            },
        }
        await self._ws.send(json.dumps(connect_msg))

        # Step 4: receive hello-ok (skip any intermediate events like tick)
        for _ in range(20):
            raw = await asyncio.wait_for(self._ws.recv(), timeout=10)
            msg = json.loads(raw)
            if msg.get("type") == "res":
                if not msg.get("ok"):
                    error_detail = json.dumps(msg.get("error", msg), default=str)[:500]
                    raise RuntimeError(f"Node handshake failed: {error_detail}")
                break
            logger.debug("Skipping pre-handshake message: %s", msg.get("type"))
        else:
            raise RuntimeError("Node handshake: too many non-res messages before hello-ok")

        self._connected = True
        logger.info("Node upstream connected for user %s", self.user_id)
        return msg

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
