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
from datetime import datetime
from typing import Any, Dict, Optional, Set

from websockets import connect as ws_connect

from core.config import TIER_CONFIG
from core.observability.metrics import put_metric, gauge
from core.repositories import channel_link_repo

GATEWAY_PORT = 18789  # OpenClaw gateway port (avoid circular import with containers/)

logger = logging.getLogger(__name__)

_HANDSHAKE_TIMEOUT = 10  # seconds
_RPC_TIMEOUT = 30  # seconds
_GRACE_PERIOD = 30  # seconds before closing idle connection
_IDLE_CHECK_INTERVAL = 60  # seconds between idle checks
_IDLE_TIMEOUT = 300  # 5 minutes of inactivity before scale-to-zero
_DDB_WRITE_COOLDOWN = 30.0  # seconds between per-owner last_active_at writes

# Per-owner cooldown map. Module-level so it survives pool reconstruction in tests
# and across pool singletons. Values are the last epoch-seconds we wrote to DDB.
_LAST_DDB_WRITE: Dict[str, float] = {}


class GatewayConnection:
    """Single persistent WebSocket to a user's OpenClaw gateway."""

    def __init__(
        self,
        user_id: str,
        ip: str,
        token: str,
        management_api: Any,
        frontend_connections: Set[str],
        conn_member_map: Dict[str, str],
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
        # Shared reference to the pool's canonical set — NOT a copy.
        self._frontend_connections = frontend_connections
        # Shared reference: connection_id → member_user_id. Used to route
        # streaming events to the specific org member who initiated the chat
        # instead of broadcasting to all members.
        self._conn_member_map = conn_member_map
        self._closed = False
        self._grace_task: Optional[asyncio.Task] = None
        self._billing_tasks: Set[asyncio.Task] = set()

    def _emit_status_change(self, state: str, reason: str) -> None:
        """Push a status_change event to all connected frontend WebSockets."""
        from datetime import datetime, timezone

        # Wrap as {type: "event"} so the frontend WS router in useGateway
        # delivers it to onEvent subscribers (unrecognized types are dropped).
        message = {
            "type": "event",
            "event": "status_change",
            "payload": {
                "state": state,
                "reason": reason,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        }
        gone: list[str] = []
        for conn_id in list(self._frontend_connections):
            try:
                if not self._management_api.send_message(conn_id, message):
                    gone.append(conn_id)
            except Exception:
                gone.append(conn_id)
        for conn_id in gone:
            self._frontend_connections.discard(conn_id)
            put_metric("gateway.frontend.prune")
            logger.info("Pruned gone frontend connection %s for user %s", conn_id, self.user_id)

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
        # Token auth: OpenClaw's trusted-proxy mode explicitly blocks loopback
        # connections (see issue #17761), making it incompatible with our
        # per-user container setup where the local agent must call its own
        # gateway. We use token mode with a per-container shared secret instead.
        # Network isolation (private VPC) provides the transport-level boundary.
        self._ws = await ws_connect(
            uri,
            open_timeout=_HANDSHAKE_TIMEOUT,
            close_timeout=5,
        )
        await self._handshake()
        await self._verify_health()
        self._reader_task = asyncio.create_task(self._reader_loop())
        put_metric("gateway.connection", dimensions={"event": "connect"})
        self._emit_status_change("HEALTHY", "Gateway connected")
        logger.info("Gateway connection established for user %s at %s", self.user_id, self.ip)

    async def _handshake(self) -> None:
        """Complete OpenClaw 4.5 connect handshake via signed-device auth.

        OpenClaw 4.5 replaced the pre-4.5 "token = admin" model with a
        scoped-auth system (see `src/gateway/method-scopes.ts` in the
        reference). A connect request that provides only `auth.token` with
        no signed device identity gets its self-declared scopes silently
        cleared by the server (`message-handler.ts:438-595`), leaving the
        connection with zero permissions — which breaks `sessions.list`
        (billing poll), `status`, and most of our RPC surface.

        To receive the scopes we actually need, we must:

        1. Hold an Ed25519 keypair (generated at provision time, seed is
           KMS-encrypted in the containers DynamoDB row).
        2. Have the public half pre-registered in the container's
           `devices/paired.json` (also written at provision time).
        3. Sign the canonical v2 payload over the nonce from
           `connect.challenge` and include the signature + public key in
           the `device` field of the connect request.

        This method does all three per connection open. The resulting device
        identity is bound by the signature to the specific gateway token +
        nonce, so captured signatures can't be replayed against different
        tokens or different connects.
        """
        from core.crypto import kms_secrets
        from core.crypto.operator_device import (
            BACKEND_CLIENT_ID,
            BACKEND_CLIENT_MODE,
            BACKEND_OPERATOR_SCOPES,
            BACKEND_ROLE,
            load_operator_device_from_seed,
            sign_connect_request,
        )
        from core.repositories import container_repo

        # Step 1: receive connect.challenge (nonce for the signature)
        raw = await asyncio.wait_for(self._ws.recv(), timeout=_HANDSHAKE_TIMEOUT)
        challenge = json.loads(raw)
        if challenge.get("event") != "connect.challenge":
            raise RuntimeError(f"Expected connect.challenge, got: {challenge.get('event', 'unknown')}")
        nonce = challenge.get("payload", {}).get("nonce") or challenge.get("nonce")
        if not nonce:
            raise RuntimeError(f"connect.challenge missing nonce: {challenge}")

        # Step 2: load the operator device identity for this container.
        # The private seed is KMS-encrypted in DynamoDB and bound by
        # encryption context to the owner_id — a stolen row can't be
        # replayed against a different container.
        container = await container_repo.get_by_owner_id(self.user_id)
        if not container:
            raise RuntimeError(f"No container row for user {self.user_id}")
        enc_seed = container.get("operator_priv_key_enc")
        if not enc_seed:
            raise RuntimeError(
                f"Container row for user {self.user_id} has no operator_priv_key_enc — "
                "re-provision needed (pre-4.5 row without signed-device auth)"
            )
        seed_bytes = kms_secrets.decrypt_bytes(
            enc_seed,
            encryption_context={"owner_id": self.user_id, "purpose": "operator-device-seed"},
        )
        identity = load_operator_device_from_seed(seed_bytes)

        # Step 3: sign the v2 payload with the nonce from the challenge.
        device = sign_connect_request(
            identity=identity,
            token=self.token,
            nonce=nonce,
            scopes=BACKEND_OPERATOR_SCOPES,
        )

        # Step 4: send the connect request with both the token AND the
        # signed device. The scopes field in params must exactly match the
        # scopes in the signed payload — the server re-builds the v2 string
        # from these fields and compares signatures.
        connect_msg = {
            "type": "req",
            "id": str(uuid.uuid4()),
            "method": "connect",
            "params": {
                "minProtocol": 3,
                "maxProtocol": 3,
                "client": {
                    "id": BACKEND_CLIENT_ID,
                    "version": "1.0.0",
                    "platform": "linux",
                    "mode": BACKEND_CLIENT_MODE,
                },
                "role": BACKEND_ROLE,
                "scopes": list(BACKEND_OPERATOR_SCOPES),
                "auth": {"token": self.token},
                "device": device,
                # Opt in to real-time tool events. Without this capability,
                # OpenClaw silently drops stream:"tool" events for this client.
                "caps": ["tool-events"],
            },
        }
        await self._ws.send(json.dumps(connect_msg))

        # Step 5: verify hello-ok
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
                put_metric("gateway.health_check.timeout")
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
        """Extract streaming text, thinking, or tool events from an OpenClaw agent event.

        Agent events fire for every LLM token (no 150ms throttle).
        - ``stream: "assistant"`` events with text are forwarded as chunks.
        - ``stream: "reasoning"`` / ``"thinking"`` events are forwarded for real-time thinking.
        - ``stream: "tool"`` events are forwarded as tool_start/tool_end/tool_error.
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

        if stream in ("reasoning", "thinking"):
            text = data.get("text", "")
            if text:
                return {"type": "thinking", "content": text}
            return None

        if stream == "tool":
            phase = data.get("phase", "")
            name = data.get("name", "")
            if not name:
                return None
            tool_call_id = data.get("toolCallId", "")
            if phase == "start":
                # OpenClaw never strips `args` — it's safe to forward at any
                # verboseLevel. Shows the user what the tool was called with.
                msg: dict = {"type": "tool_start", "tool": name}
                if tool_call_id:
                    msg["toolCallId"] = tool_call_id
                if "args" in data:
                    msg["args"] = data["args"]
                return msg
            if phase == "result":
                # OpenClaw signals tool errors via isError flag on the result
                # phase, not a separate "error" phase. `result` and `meta`
                # are only populated when verboseLevel is "full" (set in
                # agents.defaults.verboseDefault).
                is_error = bool(data.get("isError"))
                msg = {"type": "tool_error" if is_error else "tool_end", "tool": name}
                if tool_call_id:
                    msg["toolCallId"] = tool_call_id
                if "result" in data:
                    msg["result"] = data["result"]
                if data.get("meta"):
                    msg["meta"] = data["meta"]
                return msg
            return None

        return None

    @staticmethod
    def _extract_thinking_text(payload: dict) -> str | None:
        """Extract thinking/reasoning text from a chat event's message.content field."""
        msg = payload.get("message")
        if not isinstance(msg, dict):
            return None
        content = msg.get("content", [])
        if not isinstance(content, list):
            return None
        thinking_parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "thinking":
                text = block.get("thinking") or block.get("text") or ""
                if text:
                    thinking_parts.append(text)
        return "\n\n".join(thinking_parts) if thinking_parts else None

    def _forward_to_frontends(self, message: dict, target_member_id: str | None = None) -> None:
        """Send a message to registered frontend connections.

        When *target_member_id* is set, only connections belonging to that
        member receive the message (per-member event routing for orgs).
        When ``None``, broadcast to all connections (status changes, etc.).
        """
        all_conns = list(self._frontend_connections)
        if not all_conns:
            msg_type = message.get("type", "?")
            logger.warning(
                "[%s] forward: no frontend connections for msg type=%s target=%s",
                self.user_id,
                msg_type,
                target_member_id or "broadcast",
            )
            return
        gone: list[str] = []
        delivered = 0
        skipped = 0
        for conn_id in all_conns:
            if target_member_id is not None:
                # Case-insensitive: OpenClaw lowercases sessionKeys
                # internally, so the member_id parsed from the event is
                # lowercase, but conn_member_map stores the original
                # Clerk user_id (mixed case).
                member = self._conn_member_map.get(conn_id, "")
                if member.lower() != target_member_id.lower():
                    skipped += 1
                    continue
            try:
                if not self._management_api.send_message(conn_id, message):
                    gone.append(conn_id)
                else:
                    delivered += 1
            except Exception:
                logger.warning("Failed to forward message to %s", conn_id)
                gone.append(conn_id)
        for conn_id in gone:
            self._frontend_connections.discard(conn_id)
            put_metric("gateway.frontend.prune")
            logger.info("Pruned gone frontend connection %s for user %s", conn_id, self.user_id)
        # Log delivery summary for non-chunk messages (chunks are too frequent)
        msg_type = message.get("type", "?")
        if msg_type not in ("chunk",):
            logger.info(
                "[%s] forward type=%s target=%s delivered=%d skipped=%d gone=%d total=%d",
                self.user_id,
                msg_type,
                target_member_id or "broadcast",
                delivered,
                skipped,
                len(gone),
                len(all_conns),
            )

    def _record_usage_from_session(self, payload: dict) -> None:
        """Record usage after a billable event by resolving the session key
        to a member_id and querying session tokens.

        Triggered from the `agent` event lifecycle/end branch below (not
        from chat.final, which only fires for webchat and doesn't exist for
        channel-driven runs).
        """
        session_key = payload.get("sessionKey", "")
        if not session_key:
            logger.warning(
                "No sessionKey in billable event for user %s — cannot record usage",
                self.user_id,
            )
            return

        parsed = _parse_session_key(session_key)
        if not parsed:
            logger.warning(
                "Malformed sessionKey %r for user %s — cannot record usage",
                session_key,
                self.user_id,
            )
            return

        async def _resolve_then_record():
            try:
                member_id = await self._resolve_member_from_session(parsed)
                await self._fetch_and_record_usage(session_key, member_id)
            except Exception:
                # Don't let billing failures crash the gateway reader. Log
                # with full traceback so DynamoDB outages and similar
                # transient failures are observable.
                logger.exception(
                    "Failed to resolve+record usage for user %s session %s",
                    self.user_id,
                    session_key,
                )

        task = asyncio.create_task(_resolve_then_record())
        # Track the in-flight task so close() can await it on shutdown.
        # Without this, scale-to-zero teardown can cancel pending billing
        # writes mid-flight, silently losing the last few usage events.
        self._billing_tasks.add(task)
        task.add_done_callback(self._billing_tasks.discard)

    async def _resolve_member_from_session(self, parsed: dict) -> str:
        """Map a parsed session key to the Clerk member_id.

        Falls back to self.user_id (the owner) if no per-member attribution
        is available (unlinked DM, group, channel, webchat-personal, unknown).
        """
        if parsed.get("source") == "dm":
            link = await channel_link_repo.get_by_peer(
                owner_id=self.user_id,
                provider=parsed["channel"],
                agent_id=parsed["agent_id"],
                peer_id=parsed["peer_id"],
            )
            if link:
                return link.get("member_id", self.user_id)
            return self.user_id

        if parsed.get("source") == "webchat" and parsed.get("member_id"):
            return parsed["member_id"]

        return self.user_id

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
            put_metric("chat.session_usage.fetch.error")
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

            # Extract per-member routing target from sessionKey. OpenClaw
            # includes sessionKey in agent/chat event payloads (set in
            # server-chat.ts:865). For org webchat sessions the key is
            # "agent:{agentId}:{userId}" — _parse_session_key extracts
            # member_id so we can route events to the specific member
            # who initiated the chat instead of broadcasting to all org
            # members. Falls back to None (broadcast) for personal
            # sessions, channel sessions, or missing keys.
            session_key = ""
            if isinstance(payload, dict):
                session_key = payload.get("sessionKey", "")
            parsed_key = _parse_session_key(session_key) if session_key else {}
            target_member = parsed_key.get("member_id")
            # Channel-originated events (Telegram, Discord, Slack DMs, groups,
            # rooms) don't need to be forwarded to the web UI — OpenClaw's
            # channel plugin already delivers them directly to the platform.
            # Without this gate, channel responses leak into the web chat and
            # overwrite or intermix with the user's web conversation.
            session_source = parsed_key.get("source", "")
            is_channel_session = session_source in ("dm", "group", "channel")
            is_cron_session = session_source == "cron"

            # Drop noisy periodic events (health, tick) entirely — they are
            # OpenClaw-internal keep-alives and should never reach frontends.
            if event_name in ("health", "tick"):
                logger.debug(
                    "Gateway heartbeat for %s: event=%s",
                    self.user_id,
                    event_name,
                )
                return
            if event_name != "agent":
                state = payload.get("state", "") if isinstance(payload, dict) else ""
                logger.info(
                    "[%s] gateway event=%s state=%s sessionKey=%s target=%s",
                    self.user_id,
                    event_name,
                    state,
                    session_key[:60] if session_key else "-",
                    target_member or "broadcast",
                )

            if event_name == "agent":
                # Unthrottled agent events -- smooth token-by-token streaming
                stream = payload.get("stream", "")
                # Exclude token-level streams (assistant, reasoning, thinking)
                # from INFO logs — each fires per LLM token, so logging would
                # blow up CloudWatch volume on long responses.
                if stream not in ("assistant", "reasoning", "thinking", ""):
                    data = payload.get("data", {})
                    logger.info(
                        "Agent event for user %s: stream=%s phase=%s name=%s keys=%s",
                        self.user_id,
                        stream,
                        data.get("phase", ""),
                        data.get("name", ""),
                        list(data.keys()) if isinstance(data, dict) else type(data).__name__,
                    )
                # Billing: lifecycle/end fires once per completed agent run
                # for BOTH webchat and channel-driven runs (webchat's chat.final
                # only fires for webchat, so we use lifecycle/end instead).
                # Billing runs for ALL sessions (web + channel).
                if (
                    stream == "lifecycle"
                    and isinstance(payload.get("data"), dict)
                    and payload["data"].get("phase") == "end"
                ):
                    self._record_usage_from_session(payload)
                # Skip forwarding channel and cron events to the web UI.
                # Cron jobs run in isolated sessions inside OpenClaw — their
                # streaming events must not leak into a user's active web chat
                # (a cron "done" would terminate the user's streaming session).
                if is_channel_session or is_cron_session:
                    return
                transformed = self._transform_agent_event(payload)
                if transformed:
                    # Tag with agent_id so the frontend can route messages
                    # to the correct agent conversation and prevent cross-
                    # agent leakage when switching agents mid-stream.
                    event_agent_id = parsed_key.get("agent_id")
                    if event_agent_id:
                        transformed["agent_id"] = event_agent_id
                    self._forward_to_frontends(transformed, target_member)

            elif event_name == "chat":
                # Skip forwarding channel and cron chat events to the web UI.
                if is_channel_session or is_cron_session:
                    return
                # Chat events -- only terminal states.
                # Delta states are skipped; agent events handle streaming.
                state = payload.get("state", "")
                if state in ("final", "error", "aborted"):
                    logger.info(
                        "[%s] chat %s sessionKey=%s target=%s",
                        self.user_id,
                        state,
                        session_key[:60] if session_key else "-",
                        target_member or "broadcast",
                    )
                # Tag all chat messages with agent_id so the frontend can
                # route responses to the correct agent conversation.
                event_agent_id = parsed_key.get("agent_id")
                if state == "final":
                    put_metric("chat.message.count")
                    # Deliver thinking from content blocks for models that
                    # batch reasoning into the final message (reasoningLevel
                    # not set to "stream"). Once reasoningLevel:"stream" is
                    # enabled on the session, this will typically be empty
                    # because thinking streamed via agent events already.
                    thinking_text = self._extract_thinking_text(payload)
                    if thinking_text:
                        fwd: dict = {"type": "thinking", "content": thinking_text}
                        if event_agent_id:
                            fwd["agent_id"] = event_agent_id
                        self._forward_to_frontends(fwd, target_member)
                    # OpenClaw guarantees the full text reached us via agent
                    # stream="assistant" events (with flushBufferedChatDeltaIfNeeded
                    # as a server-side backstop), so no chunk is emitted here.
                    fwd = {"type": "done"}
                    if event_agent_id:
                        fwd["agent_id"] = event_agent_id
                    self._forward_to_frontends(fwd, target_member)
                elif state == "error":
                    put_metric("chat.error", dimensions={"reason": "agent_error"})
                    err = payload.get("error", {})
                    err_msg = (
                        err.get("message", "Agent run failed")
                        if isinstance(err, dict)
                        else str(err or "Agent run failed")
                    )
                    fwd = {"type": "error", "message": err_msg}
                    if event_agent_id:
                        fwd["agent_id"] = event_agent_id
                    self._forward_to_frontends(fwd, target_member)
                elif state == "aborted":
                    put_metric("chat.error", dimensions={"reason": "aborted"})
                    fwd = {"type": "error", "message": "Agent run was cancelled"}
                    if event_agent_id:
                        fwd["agent_id"] = event_agent_id
                    self._forward_to_frontends(fwd, target_member)

            else:
                # Forward other events as-is for SWR revalidation (broadcast to all)
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
            put_metric("gateway.connection", dimensions={"event": "error"})
            logger.error("Gateway reader loop error for user %s: %s", self.user_id, e)
            self._emit_status_change("GATEWAY_DOWN", "Gateway connection lost")
            # Reject all pending RPCs
            for req_id, future in list(self._pending_rpcs.items()):
                if not future.done():
                    future.set_exception(RuntimeError("Gateway connection lost"))
            self._pending_rpcs.clear()

    @property
    def has_frontend_connections(self) -> bool:
        return len(self._frontend_connections) > 0

    async def close(self) -> None:
        """Shut down: cancel reader, close WebSocket."""
        self._emit_status_change("GATEWAY_DOWN", "Gateway connection closed")
        self._closed = True
        # Wait for any in-flight billing-resolver tasks to finish writing
        # so scale-to-zero teardown doesn't drop the last few usage events.
        if self._billing_tasks:
            try:
                await asyncio.wait(
                    self._billing_tasks,
                    timeout=5.0,
                )
            except Exception:
                logger.exception(
                    "Error waiting for in-flight billing tasks during close for user %s",
                    self.user_id,
                )
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
        self._frontend_connections: Dict[str, Set[str]] = {}  # owner_id -> set of conn_ids
        self._conn_member_map: Dict[str, str] = {}  # connection_id -> member_user_id
        self._lock = asyncio.Lock()
        self._grace_tasks: Dict[str, asyncio.Task] = {}

    async def record_activity(self, owner_id: str) -> None:
        """Record a user-interaction event.

        Throttles DDB writes to at most one per owner per _DDB_WRITE_COOLDOWN
        seconds. Callers are not expected to throttle; fire for every event.

        Cooldown is claimed *before* the await to deflect a thundering herd of
        concurrent pings, but is released if the write turns out to be a no-op
        (row missing or still `status=stopped`) or if the await raises. Both
        cases need the next ping to retry immediately — most importantly on
        cold start, where the first ping can land while the row is still
        flipping from `stopped` to `running`.
        """
        now = time.time()
        last = _LAST_DDB_WRITE.get(owner_id, 0.0)
        if now - last < _DDB_WRITE_COOLDOWN:
            return
        _LAST_DDB_WRITE[owner_id] = now

        from core.dynamodb import utc_now_iso
        from core.repositories import container_repo

        try:
            wrote = await container_repo.update_last_active(owner_id, utc_now_iso())
        except Exception:
            logger.warning("record_activity: DDB write failed for %s", owner_id, exc_info=True)
            _LAST_DDB_WRITE.pop(owner_id, None)
            return

        if not wrote:
            _LAST_DDB_WRITE.pop(owner_id, None)

    async def _create_connection(self, user_id: str, ip: str, token: str) -> GatewayConnection:
        """Create and connect a new GatewayConnection."""
        # Ensure the canonical set exists before passing it as a shared
        # reference. The GatewayConnection reads this set directly when
        # fanning out events — no copy, no sync, no race.
        if user_id not in self._frontend_connections:
            self._frontend_connections[user_id] = set()
        conn = GatewayConnection(
            user_id=user_id,
            ip=ip,
            token=token,
            management_api=self._management_api,
            frontend_connections=self._frontend_connections[user_id],
            conn_member_map=self._conn_member_map,
        )
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
        try:
            return await conn.wait_for_response(req_id)
        except Exception:
            put_metric("gateway.rpc.error", dimensions={"method": method})
            raise

    def add_frontend_connection(
        self,
        user_id: str,
        connection_id: str,
        member_id: str | None = None,
    ) -> None:
        """Register a frontend WS connection for event forwarding.

        *member_id* is the Clerk user_id of the org member who owns this
        connection. For personal (non-org) users it can be ``None`` — all
        events broadcast to all connections. For org members it enables
        per-member event routing so member A only sees their own chat
        streaming, not member B's.
        """
        if user_id not in self._frontend_connections:
            self._frontend_connections[user_id] = set()
        self._frontend_connections[user_id].add(connection_id)
        if member_id:
            self._conn_member_map[connection_id] = member_id

        # Cancel grace period if one is running
        grace = self._grace_tasks.pop(user_id, None)
        if grace and not grace.done():
            grace.cancel()

    def remove_frontend_connection(self, user_id: str, connection_id: str) -> None:
        """Unregister a frontend connection. Start grace period if none remain."""
        fcs = self._frontend_connections.get(user_id)
        if fcs:
            fcs.discard(connection_id)
        self._conn_member_map.pop(connection_id, None)

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
            put_metric("gateway.connection", dimensions={"event": "disconnect"})
            await conn.close()
        self._frontend_connections.pop(user_id, None)
        self._grace_tasks.pop(user_id, None)

    async def broadcast_to_user(self, user_id: str, message: dict) -> None:
        """Send a message to all frontend connections for a user."""
        conn = self._connections.get(user_id)
        if conn:
            conn._forward_to_frontends(message)

    async def close_all(self) -> None:
        """Shutdown: close all connections."""
        for user_id in list(self._connections.keys()):
            await self.close_user(user_id)

    async def _reap_once(self) -> list[str]:
        """One pass of the reaper. Returns the list of owner_ids that were stopped.

        Extracted so the loop body is trivially testable — the test calls
        `_reap_once` directly without running the outer `asyncio.sleep` loop.

        Walks DDB (container_repo.get_by_status("running")) rather than the
        in-memory connection pool, so disconnected users whose browsers have
        closed remain candidates for reaping. That was the root bug: the old
        loop walked `self._connections`, and a user who closed their tab was
        evicted from the dict before the 5-minute timer fired — so their
        container ran forever.
        """
        from core.containers import get_ecs_manager
        from core.containers.ecs_manager import EcsManagerError
        from core.repositories import billing_repo, container_repo

        try:
            rows = await container_repo.get_by_status("running")
        except Exception:
            logger.exception("idle_checker: get_by_status failed")
            return []

        try:
            gauge("gateway.running.count", len(rows))
            # Preserve the legacy metric so the W5 alarm on gateway.connection.open
            # keeps getting datapoints. Measures active backend↔container gateway
            # WS connections (distinct from running.count, which is DDB-backed).
            gauge("gateway.connection.open", len(self._connections))
        except Exception:
            pass

        now_ts = time.time()
        stopped: list[str] = []

        for row in rows:
            owner_id = row["owner_id"]
            last_active_str = row.get("last_active_at")
            if last_active_str:
                try:
                    # Our writer emits `+00:00`, but replace a trailing `Z` so
                    # any external writer (or pre-3.11 Python) parses cleanly.
                    last_active_epoch = datetime.fromisoformat(last_active_str.replace("Z", "+00:00")).timestamp()
                except Exception:
                    last_active_epoch = 0.0
            else:
                # Deploy-day path: pre-change rows have no last_active_at.
                # Treat as epoch 0 so they're reaped on the first cycle.
                last_active_epoch = 0.0

            if now_ts - last_active_epoch < _IDLE_TIMEOUT:
                continue

            # Resolve tier; missing billing row is treated as free (orphan policy).
            try:
                account = await billing_repo.get_by_owner_id(owner_id)
            except Exception:
                logger.warning("idle_checker: billing lookup failed for %s, skipping", owner_id)
                continue
            plan_tier = (account or {}).get("plan_tier", "free")

            if not TIER_CONFIG.get(plan_tier, {}).get("scale_to_zero", False):
                continue

            try:
                await get_ecs_manager().stop_user_service(owner_id)
                await container_repo.mark_stopped_if_running(owner_id)
                put_metric("gateway.idle.scale_to_zero", dimensions={"tier": plan_tier})
                logger.info("scale-to-zero: stopped %s (tier=%s)", owner_id, plan_tier)
                stopped.append(owner_id)
            except EcsManagerError as e:
                logger.error("scale-to-zero: ECS stop failed for %s: %s", owner_id, e)
            except Exception:
                logger.exception("scale-to-zero: unexpected error for %s", owner_id)

        return stopped

    async def run_idle_checker(self) -> None:
        """Background task: every _IDLE_CHECK_INTERVAL seconds, reap idle
        free-tier (or orphan) containers using DDB as source of truth."""
        logger.info(
            "Idle checker started (interval=%ds, timeout=%ds)",
            _IDLE_CHECK_INTERVAL,
            _IDLE_TIMEOUT,
        )
        try:
            while True:
                await asyncio.sleep(_IDLE_CHECK_INTERVAL)
                await self._reap_once()
        except asyncio.CancelledError:
            logger.info("Idle checker stopped")
            return


def _parse_session_key(session_key: str) -> dict:
    """Parse an OpenClaw session key into its components.

    Shapes (from openclaw/src/routing/session-key.ts with dmScope=per-account-channel-peer):
      Personal webchat:  agent:<agentId>:main
      Org webchat:       agent:<agentId>:<clerk_user_id>
      Cron chat:         agent:<agentId>:cron:<cronId>
      Cron run event:    agent:<agentId>:cron:<cronId>:run:<runId>
      Channel DM:        agent:<agentId>:<channel>:<accountId>:direct:<peerId>
      Channel group:     agent:<agentId>:<channel>:group:<id>(:topic:<topicId>)?
      Channel room:      agent:<agentId>:<channel>:channel:<id>(:thread:<threadId>)?

    Returns dict with:
      - empty {} for malformed input
      - {agent_id, source} for webchat personal
      - {agent_id, source, member_id} for org webchat (member_id is the clerk user_id)
      - {agent_id, source, cron_id} for cron sessions (source="cron")
      - {agent_id, source, channel, peer_id} for channel DMs (source="dm")
      - {agent_id, source, channel, group_id} for channel groups (source="group")
      - {agent_id, source, channel, channel_id} for channel rooms (source="channel")
    """
    parts = session_key.split(":")
    if len(parts) < 3 or parts[0] != "agent":
        return {}
    agent_id = parts[1]

    # Cron sessions: agent:<agentId>:cron:<cronId>(:run:<runId>)?
    # Must check BEFORE webchat since 4-part cron keys would otherwise
    # fall through to channel parsing.
    if parts[2] == "cron":
        result = {
            "agent_id": agent_id,
            "source": "cron",
        }
        if len(parts) >= 4:
            result["cron_id"] = parts[3]
        return result

    # Webchat: 3 parts (agent:<agentId>:<sessionName>)
    if len(parts) == 3:
        if parts[2] == "main":
            return {"agent_id": agent_id, "source": "webchat"}
        # Org webchat — parts[2] is a Clerk user_id
        return {
            "agent_id": agent_id,
            "source": "webchat",
            "member_id": parts[2],
        }

    # Channel DM (per-account-channel-peer):
    # agent:<agentId>:<channel>:<accountId>:direct:<peerId>
    # In our design accountId == agentId so we don't extract parts[3] separately.
    if len(parts) == 6 and parts[4] == "direct":
        return {
            "agent_id": agent_id,
            "source": "dm",
            "channel": parts[2],
            "peer_id": parts[5],
        }

    # Channel group: agent:<agentId>:<channel>:group:<id>(:topic:<topicId>)?
    if len(parts) >= 5 and parts[3] == "group":
        return {
            "agent_id": agent_id,
            "source": "group",
            "channel": parts[2],
            "group_id": parts[4],
        }

    # Channel room: agent:<agentId>:<channel>:channel:<id>(:thread:<threadId>)?
    if len(parts) >= 5 and parts[3] == "channel":
        return {
            "agent_id": agent_id,
            "source": "channel",
            "channel": parts[2],
            "channel_id": parts[4],
        }

    return {"agent_id": agent_id, "source": "unknown"}
