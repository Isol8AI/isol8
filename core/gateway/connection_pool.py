# backend/core/gateway/connection_pool.py
"""
Persistent WebSocket connection pool to OpenClaw gateway containers.

Maintains one WebSocket per active user. Proxies OpenClaw's native
req/res/event protocol. Background reader task handles incoming messages:
- type=res: resolves pending RPC Futures
- type=event: forwards to user's frontend connections via Management API
"""

import asyncio
import json
import logging
import uuid
from typing import Any, Dict, Optional, Set

from websockets import connect as ws_connect

from core.containers.ecs_manager import GATEWAY_PORT

logger = logging.getLogger(__name__)

_HANDSHAKE_TIMEOUT = 10  # seconds
_CHAT_EVENTS = frozenset({"chat"})
_RPC_TIMEOUT = 30  # seconds
_GRACE_PERIOD = 30  # seconds before closing idle connection


class GatewayConnection:
    """Single persistent WebSocket to a user's OpenClaw gateway."""

    def __init__(
        self,
        user_id: str,
        ip: str,
        token: str,
        management_api: Any,
    ) -> None:
        self.user_id = user_id
        self.ip = ip
        self.token = token
        self._management_api = management_api
        self._ws: Any = None
        self._reader_task: Optional[asyncio.Task] = None
        self._pending_rpcs: Dict[str, asyncio.Future] = {}
        self._frontend_connections: Set[str] = set()
        self._closed = False
        self._grace_task: Optional[asyncio.Task] = None

    @property
    def is_connected(self) -> bool:
        if self._ws is None:
            return False
        # websockets v16 uses .state enum; older versions used .closed bool
        state = getattr(self._ws, "state", None)
        if state is not None:
            from websockets.protocol import State

            return state == State.OPEN
        return not getattr(self._ws, "closed", True)

    async def connect(self) -> None:
        """Open WebSocket, complete OpenClaw handshake, start reader."""
        uri = f"ws://{self.ip}:{GATEWAY_PORT}"
        self._ws = await ws_connect(uri, open_timeout=_HANDSHAKE_TIMEOUT, close_timeout=5)
        await self._handshake()
        self._reader_task = asyncio.create_task(self._reader_loop())
        logger.info("Gateway connection established for user %s at %s", self.user_id, self.ip)

    async def _handshake(self) -> None:
        """Complete OpenClaw connect handshake."""
        # Step 1: receive connect.challenge
        raw = await asyncio.wait_for(self._ws.recv(), timeout=_HANDSHAKE_TIMEOUT)
        challenge = json.loads(raw)
        if challenge.get("event") != "connect.challenge":
            raise RuntimeError(f"Expected connect.challenge, got: {challenge.get('event', 'unknown')}")

        # Step 2: send connect
        connect_msg = {
            "type": "req",
            "id": str(uuid.uuid4()),
            "method": "connect",
            "params": {
                "minProtocol": 3,
                "maxProtocol": 3,
                "client": {"id": "cli", "version": "1.0.0", "platform": "linux", "mode": "cli"},
                "role": "operator",
                "scopes": ["operator.admin"],
                "auth": {"token": self.token},
            },
        }
        await self._ws.send(json.dumps(connect_msg))

        # Step 3: verify hello-ok
        resp_raw = await asyncio.wait_for(self._ws.recv(), timeout=_HANDSHAKE_TIMEOUT)
        resp = json.loads(resp_raw)
        if not resp.get("ok"):
            err = resp.get("error", {}).get("message", "unknown error")
            raise RuntimeError(f"Gateway connect failed: {err}")

    async def send_rpc(self, req_id: str, method: str, params: dict) -> None:
        """Send {type: req} on the gateway WebSocket."""
        msg = {"type": "req", "id": req_id, "method": method, "params": params or {}}
        await self._ws.send(json.dumps(msg))

    async def wait_for_response(self, req_id: str, timeout: float = _RPC_TIMEOUT) -> Any:
        """Wait for the matching res message. Returns payload or raises."""
        future = asyncio.get_running_loop().create_future()
        self._pending_rpcs[req_id] = future
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending_rpcs.pop(req_id, None)
            raise
        finally:
            self._pending_rpcs.pop(req_id, None)

    @staticmethod
    def _transform_chat_event(event_name: str, payload: dict) -> dict | None:
        """Transform an OpenClaw chat event into the frontend chat message format.

        Returns a dict to send to the frontend, or None to skip the event.

        OpenClaw sends cumulative text in ``message.content[].text`` (the full
        response so far, not just the new characters).  We forward it as-is;
        the frontend replaces its display buffer on each chunk (matching how
        OpenClaw's own UI works).
        """
        if event_name != "chat":
            return None

        state = payload.get("state", "")
        if state == "delta":
            msg = payload.get("message", {})
            if isinstance(msg, dict):
                content_blocks = msg.get("content", [])
                if isinstance(content_blocks, list) and content_blocks:
                    block = content_blocks[-1]
                    if isinstance(block, dict):
                        text = block.get("text") or block.get("delta") or ""
                        if text:
                            return {"type": "chunk", "content": text}
                    elif isinstance(block, str) and block:
                        return {"type": "chunk", "content": block}
                elif isinstance(content_blocks, str) and content_blocks:
                    return {"type": "chunk", "content": content_blocks}
                # Fallback: message-level delta
                msg_delta = msg.get("delta") or ""
                if msg_delta:
                    return {"type": "chunk", "content": msg_delta}
            elif isinstance(msg, str) and msg:
                return {"type": "chunk", "content": msg}
            return None
        if state == "final":
            return {"type": "done"}
        if state == "error":
            err = payload.get("error", {})
            msg = err.get("message", "Agent run failed") if isinstance(err, dict) else str(err or "Agent run failed")
            return {"type": "error", "message": msg}
        if state == "aborted":
            return {"type": "error", "message": "Agent run was cancelled"}
        return None

    def _handle_message(self, data: dict) -> None:
        """Route an incoming gateway message."""
        msg_type = data.get("type")

        if msg_type == "res":
            req_id = data.get("id")
            future = self._pending_rpcs.get(req_id)
            if future and not future.done():
                if data.get("ok"):
                    future.set_result(data.get("payload", {}))
                else:
                    err_msg = data.get("error", {}).get("message", "RPC call rejected")
                    future.set_exception(RuntimeError(err_msg))
            return

        if msg_type == "event":
            event_name = data.get("event", "")
            payload = data.get("payload", {})

            if event_name in _CHAT_EVENTS:
                state = payload.get("state", "")
                # --- Diagnostic: trace every chat event through the pipeline ---
                msg_obj = payload.get("message", {})
                content_preview = ""
                if isinstance(msg_obj, dict):
                    cb = msg_obj.get("content", [])
                    if isinstance(cb, list) and cb:
                        block = cb[-1]
                        if isinstance(block, dict):
                            content_preview = (block.get("text") or block.get("delta") or "")[:80]
                logger.info(
                    "CHAT_EVENT user=%s state=%s content_len=%d preview=%r conns=%s",
                    self.user_id,
                    state,
                    len(content_preview),
                    content_preview[:40],
                    list(self._frontend_connections),
                )
                # --- End diagnostic ---

                transformed = self._transform_chat_event(event_name, payload)
                if transformed is None:
                    logger.info("CHAT_EVENT_SKIP user=%s state=%s (transform returned None)", self.user_id, state)
                    return
                for conn_id in list(self._frontend_connections):
                    try:
                        ok = self._management_api.send_message(conn_id, transformed)
                        logger.info(
                            "CHAT_SEND user=%s conn=%s type=%s ok=%s content_len=%d",
                            self.user_id,
                            conn_id,
                            transformed.get("type"),
                            ok,
                            len(str(transformed.get("content", ""))),
                        )
                    except Exception as exc:
                        logger.warning("CHAT_SEND_FAIL user=%s conn=%s: %s", self.user_id, conn_id, exc)
            else:
                # Forward non-chat events as-is for SWR revalidation
                for conn_id in list(self._frontend_connections):
                    try:
                        self._management_api.send_message(conn_id, data)
                    except Exception:
                        logger.warning("Failed to forward event to %s", conn_id)
            return

    async def _reader_loop(self) -> None:
        """Background task: read all messages from gateway WebSocket."""
        logger.info("READER_LOOP_START user=%s", self.user_id)
        msg_count = 0
        try:
            async for raw in self._ws:
                msg_count += 1
                try:
                    data = json.loads(raw)
                    self._handle_message(data)
                except json.JSONDecodeError:
                    logger.warning("Non-JSON message from gateway for user %s", self.user_id)
        except asyncio.CancelledError:
            logger.info("READER_LOOP_CANCELLED user=%s after %d msgs", self.user_id, msg_count)
            return
        except Exception as e:
            if self._closed:
                logger.info("READER_LOOP_CLOSED user=%s after %d msgs", self.user_id, msg_count)
                return
            logger.error("READER_LOOP_ERROR user=%s after %d msgs: %s", self.user_id, msg_count, e)
            # Reject all pending RPCs
            for req_id, future in list(self._pending_rpcs.items()):
                if not future.done():
                    future.set_exception(RuntimeError("Gateway connection lost"))
            self._pending_rpcs.clear()

    def add_frontend_connection(self, connection_id: str) -> None:
        """Register a frontend WebSocket connection for event forwarding."""
        self._frontend_connections.add(connection_id)
        if self._grace_task and not self._grace_task.done():
            self._grace_task.cancel()
            self._grace_task = None

    def remove_frontend_connection(self, connection_id: str) -> None:
        """Unregister a frontend connection."""
        self._frontend_connections.discard(connection_id)

    @property
    def has_frontend_connections(self) -> bool:
        return len(self._frontend_connections) > 0

    async def close(self) -> None:
        """Shut down: cancel reader, close WebSocket."""
        self._closed = True
        if self._grace_task and not self._grace_task.done():
            self._grace_task.cancel()
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            await self._ws.close()
        # Reject pending RPCs
        for req_id, future in list(self._pending_rpcs.items()):
            if not future.done():
                future.set_exception(RuntimeError("Connection closed"))
        self._pending_rpcs.clear()


class GatewayConnectionPool:
    """Pool of persistent gateway connections, one per active user."""

    def __init__(self, management_api: Any) -> None:
        self._management_api = management_api
        self._connections: Dict[str, GatewayConnection] = {}
        self._frontend_connections: Dict[str, Set[str]] = {}  # user_id -> set of conn_ids
        self._lock = asyncio.Lock()
        self._grace_tasks: Dict[str, asyncio.Task] = {}

    async def _create_connection(self, user_id: str, ip: str, token: str) -> GatewayConnection:
        """Create and connect a new GatewayConnection."""
        conn = GatewayConnection(
            user_id=user_id,
            ip=ip,
            token=token,
            management_api=self._management_api,
        )
        # Transfer any already-registered frontend connections
        for fc in self._frontend_connections.get(user_id, set()):
            conn.add_frontend_connection(fc)
        await conn.connect()
        self._connections[user_id] = conn
        return conn

    async def send_rpc(
        self,
        user_id: str,
        req_id: str,
        method: str,
        params: dict,
        ip: str,
        token: str,
    ) -> Any:
        """Send RPC via persistent connection (create if needed)."""
        async with self._lock:
            conn = self._connections.get(user_id)
            if conn is not None and not conn.is_connected:
                await conn.close()
                conn = None
            if conn is None:
                conn = await self._create_connection(user_id, ip, token)

        await conn.send_rpc(req_id, method, params)
        return await conn.wait_for_response(req_id)

    def add_frontend_connection(self, user_id: str, connection_id: str) -> None:
        """Register a frontend WS connection for event forwarding."""
        if user_id not in self._frontend_connections:
            self._frontend_connections[user_id] = set()
        self._frontend_connections[user_id].add(connection_id)

        # Also register on existing gateway connection
        conn = self._connections.get(user_id)
        if conn:
            conn.add_frontend_connection(connection_id)

        # Cancel grace period if one is running
        grace = self._grace_tasks.pop(user_id, None)
        if grace and not grace.done():
            grace.cancel()

    def remove_frontend_connection(self, user_id: str, connection_id: str) -> None:
        """Unregister a frontend connection. Start grace period if none remain."""
        fcs = self._frontend_connections.get(user_id)
        if fcs:
            fcs.discard(connection_id)

        conn = self._connections.get(user_id)
        if conn:
            conn.remove_frontend_connection(connection_id)

        # Start grace period if no frontend connections remain
        if not fcs and user_id in self._connections:
            self._grace_tasks[user_id] = asyncio.create_task(self._grace_close(user_id))

    async def _grace_close(self, user_id: str) -> None:
        """Wait grace period, then close gateway connection if still idle."""
        try:
            await asyncio.sleep(_GRACE_PERIOD)
            fcs = self._frontend_connections.get(user_id, set())
            if not fcs:
                await self.close_user(user_id)
        except asyncio.CancelledError:
            pass

    async def close_user(self, user_id: str) -> None:
        """Close gateway connection for a user."""
        conn = self._connections.pop(user_id, None)
        if conn:
            await conn.close()
        self._frontend_connections.pop(user_id, None)
        self._grace_tasks.pop(user_id, None)

    async def close_all(self) -> None:
        """Shutdown: close all connections."""
        for user_id in list(self._connections.keys()):
            await self.close_user(user_id)
