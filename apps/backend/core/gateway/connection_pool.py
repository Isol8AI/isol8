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
import time
import uuid
from typing import Any, Dict, Optional, Set

from websockets import connect as ws_connect

GATEWAY_PORT = 18789  # OpenClaw gateway port (avoid circular import with containers/)

logger = logging.getLogger(__name__)

_HANDSHAKE_TIMEOUT = 10  # seconds
_RPC_TIMEOUT = 30  # seconds
_GRACE_PERIOD = 30  # seconds before closing idle connection
_IDLE_CHECK_INTERVAL = 60  # seconds between idle checks
_IDLE_TIMEOUT = 300  # 5 minutes of inactivity before scale-to-zero


class GatewayConnection:
    """Single persistent WebSocket to a user's OpenClaw gateway."""

    def __init__(
        self,
        user_id: str,
        ip: str,
        token: str,
        management_api: Any,
        on_activity: Any = None,
    ) -> None:
        self.user_id = user_id
        self.ip = ip
        self.token = token
        self._management_api = management_api
        self._on_activity = on_activity  # callback(user_id) for idle tracking
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
        """Open WebSocket, complete OpenClaw handshake, verify health, start reader."""
        uri = f"ws://{self.ip}:{GATEWAY_PORT}"
        # Pass user identity header on the WebSocket upgrade request.
        # OpenClaw trusted-proxy auth reads x-forwarded-user from the HTTP
        # upgrade headers to identify the user without device pairing.
        self._ws = await ws_connect(
            uri,
            open_timeout=_HANDSHAKE_TIMEOUT,
            close_timeout=5,
            additional_headers={"x-forwarded-user": self.user_id},
        )
        await self._handshake()
        await self._verify_health()
        self._reader_task = asyncio.create_task(self._reader_loop())
        logger.info("Gateway connection established for user %s at %s", self.user_id, self.ip)

    async def _handshake(self) -> None:
        """Complete OpenClaw connect handshake via trusted proxy auth.

        The gateway is configured with gateway.auth.mode = "trusted-proxy".
        It trusts connections from the VPC CIDR (10.0.0.0/8) and reads user
        identity from the x-forwarded-user header passed in the connect params.
        No device pairing or Ed25519 signing needed.
        """
        # Step 1: receive connect.challenge
        raw = await asyncio.wait_for(self._ws.recv(), timeout=_HANDSHAKE_TIMEOUT)
        challenge = json.loads(raw)
        if challenge.get("event") != "connect.challenge":
            raise RuntimeError(f"Expected connect.challenge, got: {challenge.get('event', 'unknown')}")

        # Step 2: send connect request — trusted proxy handles auth at transport
        # level (IP check), so we send a standard connect with no device block.
        connect_msg = {
            "type": "req",
            "id": str(uuid.uuid4()),
            "method": "connect",
            "params": {
                "minProtocol": 3,
                "maxProtocol": 3,
                "client": {
                    "id": "gateway-client",
                    "version": "1.0.0",
                    "platform": "linux",
                    "mode": "backend",
                },
                "role": "operator",
                "scopes": ["operator.admin"],
            },
        }
        await self._ws.send(json.dumps(connect_msg))

        # Step 3: verify hello-ok
        resp_raw = await asyncio.wait_for(self._ws.recv(), timeout=_HANDSHAKE_TIMEOUT)
        resp = json.loads(resp_raw)
        if not resp.get("ok"):
            err = resp.get("error", {}).get("message", "unknown error")
            raise RuntimeError(f"Gateway connect failed: {err}")

    async def _verify_health(self) -> None:
        """Send health RPC to verify gateway is operational after handshake.

        Called before the reader loop starts, so we read responses directly
        from the WebSocket. Any interleaved events are discarded (no
        in-progress work should exist on a fresh connection).
        """
        req_id = str(uuid.uuid4())
        msg = {"type": "req", "id": req_id, "method": "health", "params": {}}
        await self._ws.send(json.dumps(msg))

        deadline = asyncio.get_event_loop().time() + _HANDSHAKE_TIMEOUT
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise RuntimeError("Gateway health check timed out")

            raw = await asyncio.wait_for(self._ws.recv(), timeout=remaining)
            data = json.loads(raw)

            # Skip any events that arrive before our health response
            if data.get("type") != "res" or data.get("id") != req_id:
                continue

            if not data.get("ok"):
                err = data.get("error", {}).get("message", "unknown")
                raise RuntimeError(f"Gateway not healthy: {err}")

            logger.debug("Health check passed for user %s", self.user_id)
            return

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
    def _transform_agent_event(payload: dict) -> dict | None:
        """Extract streaming text or tool events from an OpenClaw agent event.

        Agent events fire for every LLM token (no 150ms throttle).
        - ``stream: "assistant"`` events with text are forwarded as chunks.
        - ``stream: "tool"`` events are forwarded as tool_start/tool_end.
        """
        stream = payload.get("stream")
        data = payload.get("data")
        if not isinstance(data, dict):
            return None

        if stream == "assistant":
            text = data.get("text", "")
            if text:
                return {"type": "chunk", "content": text}
            return None

        if stream == "tool":
            phase = data.get("phase", "")
            name = data.get("name", "")
            if not name:
                return None
            if phase == "start":
                return {"type": "tool_start", "tool": name}
            if phase == "result":
                return {"type": "tool_end", "tool": name}
            return None

        return None

    @staticmethod
    def _extract_chat_text(payload: dict) -> str | None:
        """Extract text from a chat event's message.content field."""
        msg = payload.get("message")
        if not isinstance(msg, dict):
            return None
        content = msg.get("content", [])
        if isinstance(content, list) and content:
            block = content[-1]
            if isinstance(block, dict):
                return block.get("text") or None
        return None

    def _forward_to_frontends(self, message: dict) -> None:
        """Send a message to all registered frontend connections."""
        if self._on_activity:
            self._on_activity(self.user_id)
        for conn_id in list(self._frontend_connections):
            try:
                self._management_api.send_message(conn_id, message)
            except Exception:
                logger.warning("Failed to forward message to %s", conn_id)

    def _record_usage_from_session(self, payload: dict) -> None:
        """Record usage after chat.final by querying the session for token counts.

        The chat.final event itself doesn't contain token counts. We extract
        the sessionKey from the payload, parse the member user_id from it
        (org sessions use format agent:{agentId}:{userId}), then fire an
        async task that calls sessions.list RPC to get the actual token data
        and records it via usage_service.
        """
        session_key = payload.get("sessionKey", "")
        logger.info(
            "chat.final for user %s: sessionKey=%s payload_keys=%s",
            self.user_id,
            session_key or "(empty)",
            list(payload.keys()),
        )
        if not session_key:
            logger.warning("No sessionKey in chat.final for user %s — cannot record usage", self.user_id)
            return

        # Extract member user_id from session key: "agent:{agentId}:{target}"
        # For org members, target is the user_id. For personal, it's "main".
        parts = session_key.split(":")
        member_user_id = parts[2] if len(parts) >= 3 and parts[2] != "main" else self.user_id
        logger.info("Usage: querying sessions.list for session=%s member=%s", session_key, member_user_id)

        asyncio.create_task(self._fetch_and_record_usage(session_key, member_user_id))

    async def _fetch_and_record_usage(self, session_key: str, member_user_id: str) -> None:
        """Fetch session token counts via RPC and record usage."""
        try:
            # Query sessions.list to get token data for this session
            req_id = str(uuid.uuid4())
            await self.send_rpc(req_id, "sessions.list", {})
            result = await self.wait_for_response(req_id, timeout=10)

            if not isinstance(result, dict):
                logger.warning(
                    "sessions.list returned non-dict for user %s: type=%s",
                    self.user_id,
                    type(result).__name__,
                )
                return

            # Find our session in the list.
            # sessions.list returns "key" (not "sessionKey"), and chat.final
            # lowercases the session key, so compare case-insensitively.
            sessions = result.get("sessions", [])
            session_key_lower = session_key.lower()
            logger.info(
                "sessions.list returned %d sessions for user %s, looking for %s",
                len(sessions),
                self.user_id,
                session_key,
            )
            session = None
            for s in sessions:
                s_key = s.get("key", "")
                if s_key.lower() == session_key_lower:
                    session = s
                    break

            if not session:
                available_keys = [s.get("key", "?") for s in sessions[:5]]
                logger.warning(
                    "Session %s not found for user %s. Available: %s",
                    session_key,
                    self.user_id,
                    available_keys,
                )
                return

            input_tokens = int(session.get("inputTokens", 0) or 0)
            output_tokens = int(session.get("outputTokens", 0) or 0)
            cache_read = int(session.get("cacheRead", 0) or 0)
            cache_write = int(session.get("cacheWrite", 0) or 0)
            model = session.get("model") or "unknown"

            logger.info(
                "Session %s tokens: in=%d out=%d cache_r=%d cache_w=%d model=%s",
                session_key,
                input_tokens,
                output_tokens,
                cache_read,
                cache_write,
                model,
            )

            if input_tokens <= 0 and output_tokens <= 0:
                logger.warning(
                    "Zero tokens in session %s for user %s — session keys: %s",
                    session_key,
                    self.user_id,
                    list(session.keys()),
                )
                return

            # Record usage directly
            try:
                from core.services.usage_service import record_usage

                await record_usage(
                    owner_id=self.user_id,
                    user_id=member_user_id,
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_read=cache_read,
                    cache_write=cache_write,
                )
                logger.info(
                    "Recorded usage for user %s (member=%s): model=%s in=%d out=%d",
                    self.user_id,
                    member_user_id,
                    model,
                    input_tokens,
                    output_tokens,
                )
            except Exception:
                logger.exception("Failed to record usage for user %s", self.user_id)

        except Exception:
            logger.exception("Failed to fetch session usage for user %s", self.user_id)

    def _handle_message(self, data: dict) -> None:
        """Route an incoming gateway message.

        Event routing:
        - ``agent`` events (unthrottled): token-by-token streaming via
          ``_transform_agent_event``.
        - ``chat`` events: only terminal states (final/error/aborted). Delta
          states are ignored because agent events provide the same data without
          the 150ms throttle.
        - Other events: forwarded as-is for SWR revalidation.
        """
        msg_type = data.get("type")

        if msg_type == "res":
            req_id = data.get("id")
            future = self._pending_rpcs.get(req_id)
            if future and not future.done():
                if data.get("ok"):
                    future.set_result(data.get("payload", {}))
                else:
                    # Serialize the full error object so details/issues survive
                    err_obj = data.get("error", {})
                    if isinstance(err_obj, dict):
                        err_msg = json.dumps(err_obj)
                    else:
                        err_msg = str(err_obj or "RPC call rejected")
                    future.set_exception(RuntimeError(err_msg))
            return

        if msg_type == "event":
            event_name = data.get("event", "")
            payload = data.get("payload", {})

            # Log all non-agent events for debugging usage pipeline
            if event_name != "agent":
                state = payload.get("state", "") if isinstance(payload, dict) else ""
                logger.info(
                    "Gateway event for user %s: event=%s state=%s",
                    self.user_id,
                    event_name,
                    state,
                )

            if event_name == "agent":
                # Unthrottled agent events -- smooth token-by-token streaming
                stream = payload.get("stream", "")
                if stream not in ("assistant", ""):
                    # Log non-assistant events (tool, lifecycle, error) for debugging
                    data = payload.get("data", {})
                    logger.info(
                        "Agent event for user %s: stream=%s phase=%s name=%s keys=%s",
                        self.user_id,
                        stream,
                        data.get("phase", ""),
                        data.get("name", ""),
                        list(data.keys()) if isinstance(data, dict) else type(data).__name__,
                    )
                transformed = self._transform_agent_event(payload)
                if transformed:
                    self._forward_to_frontends(transformed)

            elif event_name == "chat":
                # Chat events -- only terminal states.
                # Delta states are skipped; agent events handle streaming.
                state = payload.get("state", "")
                if state == "final":
                    # Send complete text as safety net before done signal
                    final_text = self._extract_chat_text(payload)
                    if final_text:
                        self._forward_to_frontends({"type": "chunk", "content": final_text})
                    self._forward_to_frontends({"type": "done"})
                    # Record usage by querying session for token counts
                    self._record_usage_from_session(payload)
                elif state == "error":
                    err = payload.get("error", {})
                    msg = (
                        err.get("message", "Agent run failed")
                        if isinstance(err, dict)
                        else str(err or "Agent run failed")
                    )
                    self._forward_to_frontends({"type": "error", "message": msg})
                elif state == "aborted":
                    self._forward_to_frontends({"type": "error", "message": "Agent run was cancelled"})

            else:
                # Forward other events as-is for SWR revalidation
                self._forward_to_frontends(data)
            return

    async def _reader_loop(self) -> None:
        """Background task: read all messages from gateway WebSocket."""
        try:
            async for raw in self._ws:
                try:
                    data = json.loads(raw)
                    self._handle_message(data)
                except json.JSONDecodeError:
                    logger.warning("Non-JSON message from gateway for user %s", self.user_id)
        except asyncio.CancelledError:
            return
        except Exception as e:
            if self._closed:
                return
            logger.error("Gateway reader loop error for user %s: %s", self.user_id, e)
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

    def __init__(
        self,
        management_api: Any,
    ) -> None:
        self._management_api = management_api
        self._connections: Dict[str, GatewayConnection] = {}
        self._frontend_connections: Dict[str, Set[str]] = {}  # user_id -> set of conn_ids
        self._lock = asyncio.Lock()
        self._grace_tasks: Dict[str, asyncio.Task] = {}
        self._last_activity: Dict[str, float] = {}  # user_id -> last activity timestamp

    def _touch_activity(self, user_id: str) -> None:
        """Update last activity timestamp for a user."""
        self._last_activity[user_id] = time.time()

    async def _create_connection(self, user_id: str, ip: str, token: str) -> GatewayConnection:
        """Create and connect a new GatewayConnection."""
        conn = GatewayConnection(
            user_id=user_id,
            ip=ip,
            token=token,
            management_api=self._management_api,
            on_activity=self._touch_activity,
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
        self._last_activity[user_id] = time.time()
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
        self._last_activity[user_id] = time.time()
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
        self._last_activity.pop(user_id, None)

    async def close_all(self) -> None:
        """Shutdown: close all connections."""
        for user_id in list(self._connections.keys()):
            await self.close_user(user_id)

    async def run_idle_checker(self) -> None:
        """Background task: stop free-tier containers after 5 minutes of inactivity.

        Runs every 60 seconds. For each user in the pool, checks:
        1. No frontend connections (no active WebSocket clients)
        2. No activity for 5 minutes
        3. User is on free tier (billing_repo.get_by_owner_id)

        If all conditions are met, stops the container via ECS and closes
        the gateway connection.
        """
        from core.containers.ecs_manager import EcsManagerError

        logger.info("Idle checker started (interval=%ds, timeout=%ds)", _IDLE_CHECK_INTERVAL, _IDLE_TIMEOUT)
        try:
            while True:
                await asyncio.sleep(_IDLE_CHECK_INTERVAL)
                now = time.time()

                # Snapshot user_ids with active connections
                user_ids = list(self._connections.keys())
                for user_id in user_ids:
                    # Skip if user has active frontend connections
                    fcs = self._frontend_connections.get(user_id, set())
                    if fcs:
                        continue

                    # Skip if recent activity
                    last = self._last_activity.get(user_id, now)
                    if now - last < _IDLE_TIMEOUT:
                        continue

                    # Check if user is on the free tier
                    try:
                        from core.repositories import billing_repo

                        account = await billing_repo.get_by_owner_id(user_id)
                        if not account or account.get("plan_tier") != "free":
                            continue
                    except Exception:
                        logger.warning("Idle checker: failed to look up billing for user %s, skipping", user_id)
                        continue

                    # Scale to zero
                    try:
                        from core.containers import get_ecs_manager

                        await get_ecs_manager().stop_user_service(user_id)
                        await self.close_user(user_id)
                        logger.info("Scale-to-zero: stopped container for idle free user %s", user_id)
                    except EcsManagerError as e:
                        logger.error("Scale-to-zero: failed to stop container for user %s: %s", user_id, e)
                    except Exception:
                        logger.exception("Scale-to-zero: unexpected error for user %s", user_id)
        except asyncio.CancelledError:
            logger.info("Idle checker stopped")
            return
