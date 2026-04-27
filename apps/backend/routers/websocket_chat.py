"""
HTTP routes for API Gateway WebSocket integration.

API Gateway WebSocket converts WebSocket frames into HTTP POST requests:
- $connect  -> POST /ws/connect
- $disconnect -> POST /ws/disconnect
- $default (messages) -> POST /ws/message

Responses are pushed via Management API, not returned in HTTP response body.
"""

import asyncio
import json
import logging
import secrets
from typing import Any, Dict, Optional
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Response

from core.containers import get_ecs_manager, get_gateway_pool
from core.observability.metrics import put_metric
from core.services.connection_service import ConnectionService, ConnectionServiceError
from core.services.management_api_client import ManagementApiClient
from routers.node_proxy import (
    handle_node_connect,
    handle_node_message,
    handle_node_disconnect,
    is_node_connection,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


# Singleton instances (created lazily with async lock for thread safety)
_connection_service: Optional[ConnectionService] = None
_management_api_client: Optional[ManagementApiClient] = None
_singleton_lock = asyncio.Lock()


async def get_connection_service() -> ConnectionService:
    """Get or create ConnectionService singleton (async-safe)."""
    global _connection_service
    if _connection_service is None:
        async with _singleton_lock:
            if _connection_service is None:
                _connection_service = ConnectionService()
    return _connection_service


async def get_management_api_client() -> ManagementApiClient:
    """Get or create ManagementApiClient singleton (async-safe)."""
    global _management_api_client
    if _management_api_client is None:
        async with _singleton_lock:
            if _management_api_client is None:
                _management_api_client = ManagementApiClient()
    return _management_api_client


async def _safe_record_usage(**kwargs) -> None:
    """Record usage, catching errors so they never propagate."""
    try:
        from core.services.usage_service import record_usage

        await record_usage(**kwargs)
    except Exception:
        logger.exception("Usage recording failed for owner %s", kwargs.get("owner_id"))


async def _send_connect_challenge(connection_id: str) -> None:
    """Send OpenClaw connect.challenge to a newly connected client.

    The control UI SPA expects this event before sending its connect
    handshake.  The chat frontend ignores it (no ``type`` field).
    """
    try:
        management_api = await get_management_api_client()
        management_api.send_message(
            connection_id,
            {
                "type": "event",
                "event": "connect.challenge",
                "payload": {"nonce": secrets.token_urlsafe(16)},
            },
        )
    except Exception as e:
        logger.warning("Failed to send connect.challenge to %s: %s", connection_id, e)


@router.post(
    "/connect",
    status_code=200,
    summary="Handle WebSocket connect",
    description="Called by API Gateway on $connect. Stores connection state in DynamoDB.",
    operation_id="ws_connect",
    responses={
        400: {"description": "Missing x-connection-id header"},
        401: {"description": "Missing x-user-id header"},
    },
)
async def ws_connect(
    background_tasks: BackgroundTasks,
    x_connection_id: Optional[str] = Header(None, alias="x-connection-id"),
    x_user_id: Optional[str] = Header(None, alias="x-user-id"),
    x_org_id: Optional[str] = Header(None, alias="x-org-id"),
) -> Response:
    if not x_connection_id:
        raise HTTPException(status_code=400, detail="Missing x-connection-id header")
    if not x_user_id:
        raise HTTPException(status_code=401, detail="Missing x-user-id header")

    logger.info(
        "WS connect: conn=%s user=%s org=%s owner=%s",
        x_connection_id[:12],
        x_user_id,
        x_org_id or "-",
        x_org_id or x_user_id,
    )

    connection_service = await get_connection_service()
    connection_service.store_connection(
        connection_id=x_connection_id,
        user_id=x_user_id,
        org_id=x_org_id,
    )

    try:
        pool = get_gateway_pool()
        # Route by owner_id: org_id for org members, user_id for personal
        owner_id = x_org_id or x_user_id
        # Pass member_id so the pool can route streaming events to the
        # specific org member who initiated each chat, not broadcast to
        # all members. For personal users member_id == owner_id so it's
        # harmless (the filter matches all connections).
        pool.add_frontend_connection(owner_id, x_connection_id, member_id=x_user_id)
    except Exception as e:
        logger.warning("Failed to register frontend connection with pool: %s", e)

    # Send OpenClaw connect.challenge so the control UI SPA can complete
    # its handshake.  The chat frontend silently ignores this message.
    background_tasks.add_task(_send_connect_challenge, x_connection_id)

    return Response(status_code=200)


@router.post(
    "/disconnect",
    status_code=200,
    summary="Handle WebSocket disconnect",
    description="Called by API Gateway on $disconnect. Removes connection state from DynamoDB.",
    operation_id="ws_disconnect",
)
async def ws_disconnect(
    x_connection_id: Optional[str] = Header(None, alias="x-connection-id"),
) -> Response:
    if not x_connection_id:
        return Response(status_code=200)

    logger.info("WebSocket disconnect: connection_id=%s", x_connection_id)

    # Unregister from gateway connection pool
    try:
        connection_service = await get_connection_service()
        connection = connection_service.get_connection(x_connection_id)
        if connection:
            owner_id = connection.get("org_id") or connection["user_id"]
            user_id = connection["user_id"]

            # Always unregister from the frontend fanout pool: every WS
            # (node OR chat) gets added in ws_connect, so every close path
            # must remove it. Previously the node branch skipped this call
            # and dead sockets lingered in _frontend_connections, causing
            # every subsequent broadcast to retry a doomed send.
            pool = get_gateway_pool()
            pool.remove_frontend_connection(owner_id, x_connection_id)

            # Additionally tear down the node upstream + per-user state
            # if this was a node connection.
            if is_node_connection(x_connection_id):
                await handle_node_disconnect(x_connection_id, owner_id, user_id)
    except Exception as e:
        logger.warning("Failed to unregister frontend connection from pool: %s", e)

    try:
        connection_service = await get_connection_service()
        connection_service.delete_connection(x_connection_id)
    except ConnectionServiceError as e:
        logger.warning("Failed to delete connection %s: %s", x_connection_id, e)
    except Exception as e:
        logger.exception("Unexpected error deleting connection %s: %s", x_connection_id, e)

    return Response(status_code=200)


@router.post(
    "/message",
    status_code=200,
    summary="Handle WebSocket message",
    description="Called by API Gateway on $default. Processes agent chat messages and pushes responses via Management API.",
    operation_id="ws_message",
    responses={
        400: {"description": "Missing x-connection-id header"},
        401: {"description": "Unknown connection (not in DynamoDB)"},
    },
)
async def ws_message(
    body: Dict[str, Any],
    background_tasks: BackgroundTasks,
    x_connection_id: Optional[str] = Header(None, alias="x-connection-id"),
) -> Response:
    if not x_connection_id:
        raise HTTPException(status_code=400, detail="Missing x-connection-id header")

    connection_service = await get_connection_service()
    connection = connection_service.get_connection(x_connection_id)

    if not connection:
        raise HTTPException(status_code=401, detail="Unknown connection")

    user_id = connection["user_id"]
    owner_id = connection.get("org_id") or user_id
    msg_type = body.get("type")

    if msg_type == "ping":
        management_api = await get_management_api_client()
        management_api.send_message(x_connection_id, {"type": "pong"})
        return Response(status_code=200)

    # Log all non-ping message types so chat/RPC flow is visible at INFO
    logger.info(
        "[%s] ws msg type=%s owner=%s conn=%s method=%s agent=%s",
        user_id,
        msg_type,
        owner_id,
        x_connection_id[:12] if x_connection_id else "?",
        body.get("method", "-") if msg_type == "req" else "-",
        body.get("agent_id", "-") if msg_type == "agent_chat" else "-",
    )

    if msg_type == "pong":
        return Response(status_code=200)

    if msg_type == "req":
        req_id = body.get("id")
        method = body.get("method")
        params = body.get("params", {})

        if not req_id or not method:
            management_api = await get_management_api_client()
            management_api.send_message(
                x_connection_id,
                {
                    "type": "res",
                    "id": req_id,
                    "ok": False,
                    "error": {"message": "Missing id or method"},
                },
            )
            return Response(status_code=200)

        # OpenClaw connect handshake.
        if method == "connect":
            connect_params = params or {}
            role = connect_params.get("role", "operator")

            # Node connection: open dedicated upstream with role:"node"
            if role == "node":
                conn_svc = await get_connection_service()
                conn_svc.store_connection(x_connection_id, user_id, connection.get("org_id"), connection_type="node")
                management_api = await get_management_api_client()
                try:
                    hello = await handle_node_connect(
                        owner_id=owner_id,
                        user_id=user_id,
                        connection_id=x_connection_id,
                        connect_params=connect_params,
                        management_api=management_api,
                    )
                    if hello:
                        # Rewrite the upstream's res.id to match the desktop's
                        # req.id. handle_node_connect opens a SEPARATE upstream
                        # WS to the container with its own uuid and gets back
                        # a hello res keyed on that upstream id — forwarding
                        # verbatim would break JSON-RPC correlation on the
                        # desktop, which expects res.id == req.id for the
                        # handshake.
                        management_api.send_message(x_connection_id, {**hello, "id": req_id})
                except Exception as e:
                    logger.error("Node connect failed: %s", e)
                    management_api.send_message(
                        x_connection_id,
                        {
                            "type": "res",
                            "id": req_id,
                            "ok": False,
                            "error": {"message": str(e)},
                        },
                    )
                return Response(status_code=200)

            # Operator connect — respond with hello-ok locally.
            # Auth is already handled by the Lambda authorizer.
            management_api = await get_management_api_client()
            management_api.send_message(
                x_connection_id,
                {
                    "type": "res",
                    "id": req_id,
                    "ok": True,
                    "payload": {"protocol": 3},
                },
            )
            return Response(status_code=200)

        # Node connections: relay all non-connect messages to upstream
        if is_node_connection(x_connection_id):
            await handle_node_message(x_connection_id, body)
            return Response(status_code=200)

        background_tasks.add_task(
            _process_rpc_background,
            connection_id=x_connection_id,
            user_id=user_id,
            owner_id=owner_id,
            req_id=req_id,
            method=method,
            params=params,
        )
        return Response(status_code=200)

    if msg_type == "usage":
        asyncio.create_task(
            _safe_record_usage(
                owner_id=owner_id,
                user_id=user_id,
                model=body.get("model", "unknown"),
                input_tokens=body.get("inputTokens", 0),
                output_tokens=body.get("outputTokens", 0),
                cache_read=body.get("cacheRead", 0),
                cache_write=body.get("cacheWrite", 0),
            )
        )
        return Response(status_code=200)

    if msg_type == "user_active":
        # Legacy heartbeat from useActivityPing (frontend hook is deleted in
        # the flat-fee cutover but a stray client may still send this). 200 OK
        # so we don't 4xx old browsers; the ping does nothing post-cutover.
        return Response(status_code=200)

    if msg_type == "agent_chat":
        agent_id = body.get("agent_id")
        message = body.get("message")

        if not agent_id or not message:
            management_api = await get_management_api_client()
            # No agent_id to tag — this is a client-validation error,
            # untagged by necessity. Frontend treats untagged errors as
            # broadcast so they still clear the streaming state.
            management_api.send_message(
                x_connection_id,
                {"type": "error", "message": "Missing agent_id or message"},
            )
            return Response(status_code=200)

        # The gateway connection pool's gate_chat (called inside the
        # forwarder) is the authoritative pre-chat budget gate for card-3
        # (bedrock_claude) users; cards 1 + 2 carry their own provider
        # auth and don't need a backend gate.
        background_tasks.add_task(
            _process_agent_chat_background,
            connection_id=x_connection_id,
            user_id=user_id,
            owner_id=owner_id,
            agent_id=agent_id,
            message=message,
        )
        return Response(status_code=200)

    # Unknown message type
    management_api = await get_management_api_client()
    management_api.send_message(
        x_connection_id,
        {"type": "error", "message": f"Unknown message type: {msg_type}"},
    )
    return Response(status_code=200)


# =============================================================================
# OpenClaw RPC Proxy
# =============================================================================


async def _process_rpc_background(
    connection_id: str,
    user_id: str,
    owner_id: str,
    req_id: str,
    method: str,
    params: dict,
) -> None:
    """Process an OpenClaw RPC request via the gateway connection pool."""
    # Log non-noisy RPCs at INFO (skip health/channels.status which fire every 3s)
    if method not in ("health", "channels.status"):
        logger.info("[%s] rpc %s owner=%s conn=%s", user_id, method, owner_id, connection_id[:12])
    management_api = await get_management_api_client()

    try:
        ecs_manager = get_ecs_manager()
        container, ip = await ecs_manager.resolve_running_container(owner_id)

        if not container:
            management_api.send_message(
                connection_id,
                {
                    "type": "res",
                    "id": req_id,
                    "ok": False,
                    "error": {"message": "No container provisioned."},
                },
            )
            return

        if not ip:
            management_api.send_message(
                connection_id,
                {
                    "type": "res",
                    "id": req_id,
                    "ok": False,
                    "error": {"message": "Container is starting up. Try again in a moment."},
                },
            )
            return

        pool = get_gateway_pool()
        result = await pool.send_rpc(
            user_id=owner_id,
            req_id=req_id,
            method=method,
            params=params,
            ip=ip,
            token=container["gateway_token"],
        )
        management_api.send_message(
            connection_id,
            {
                "type": "res",
                "id": req_id,
                "ok": True,
                "payload": result,
            },
        )

        # Reconcile EFS after a successful agents.delete: OpenClaw's
        # moveToTrashBestEffort silently fails on Linux containers (cross-device
        # rename from EFS to the local overlay's $HOME/.Trash), leaking the
        # agent's on-EFS dirs forever. Clean them up from the backend.
        #
        # `cleanup_agent_dirs` is sync (`shutil.rmtree`) and EFS-backed dirs
        # can be large enough to block the event loop and stall unrelated
        # WS chat traffic, so it runs on a worker thread via `to_thread`.
        if method == "agents.delete":
            agent_id = (params or {}).get("agentId")
            if isinstance(agent_id, str) and agent_id:
                try:
                    from core.containers import get_workspace

                    await asyncio.to_thread(get_workspace().cleanup_agent_dirs, owner_id, agent_id)
                except Exception as cleanup_exc:
                    logger.warning(
                        "[%s] post-delete cleanup failed for agent=%s: %s",
                        owner_id,
                        agent_id,
                        cleanup_exc,
                    )

    except RuntimeError as e:
        # RuntimeError comes from OpenClaw rejecting the RPC — forward full error object.
        # connection_pool serializes the gateway error dict as JSON in the message.
        logger.warning("RPC %s rejected for user %s: %s", method, user_id, e)
        try:
            try:
                error_obj = json.loads(str(e))
            except (ValueError, TypeError):
                error_obj = {"message": str(e)}
            management_api.send_message(
                connection_id,
                {
                    "type": "res",
                    "id": req_id,
                    "ok": False,
                    "error": error_obj,
                },
            )
        except Exception:
            pass
    except Exception as e:
        logger.error("RPC %s failed for user %s: %s", method, user_id, e)
        try:
            management_api.send_message(
                connection_id,
                {
                    "type": "res",
                    "id": req_id,
                    "ok": False,
                    "error": {"message": f"Internal error: {e}"},
                },
            )
        except Exception:
            pass


# =============================================================================
# Agent Chat (Streaming, Plaintext)
# =============================================================================


async def _process_agent_chat_background(
    connection_id: str,
    user_id: str,
    owner_id: str,
    agent_id: str,
    message: str,
) -> None:
    """
    Process agent chat message via OpenClaw's native chat.send RPC.

    Sends the message through the persistent WebSocket connection pool.
    The RPC returns immediately with an ack; streaming response events
    (text_delta, turn_completed, etc.) are handled by the pool's reader
    task and forwarded to the frontend automatically.
    """
    logger.info(
        "[%s] chat.send START agent=%s owner=%s conn=%s msg_len=%d",
        user_id,
        agent_id,
        owner_id,
        connection_id[:12],
        len(message),
    )

    management_api = await get_management_api_client()

    try:
        # Look up user's container and discover task IP
        ecs_manager = get_ecs_manager()
        container, ip = await ecs_manager.resolve_running_container(owner_id)

        if not container:
            put_metric("chat.error", dimensions={"reason": "container_unreachable"})
            logger.warning("[%s] chat.send FAIL: no container for owner=%s", user_id, owner_id)
            management_api.send_message(
                connection_id,
                {
                    "type": "error",
                    "agent_id": agent_id,
                    "message": "No container provisioned. Please subscribe to start chatting.",
                },
            )
            return

        if not ip:
            put_metric("chat.error", dimensions={"reason": "container_unreachable"})
            logger.warning("[%s] chat.send FAIL: no IP for owner=%s (container starting)", user_id, owner_id)
            management_api.send_message(
                connection_id,
                {
                    "type": "error",
                    "agent_id": agent_id,
                    "message": "Your agent is starting up. Please try again in a moment.",
                },
            )
            return

        pool = get_gateway_pool()
        req_id = str(uuid4())

        # Session key format: agent:{agentId}:{userId}
        # Every user gets their own session, isolating their chat history
        # from cron jobs, channels, and other system activity.
        session_key = f"agent:{agent_id}:{user_id}"

        logger.info(
            "[%s] chat.send RPC agent=%s sessionKey=%s ip=%s",
            user_id,
            agent_id,
            session_key,
            ip,
        )

        # --- Node binding: pin this session to the user's Mac if connected ---
        from routers.node_proxy import get_user_node, get_patched_session, set_patched_session

        node_info = get_user_node(user_id)
        if node_info:
            node_id = node_info["nodeId"]
            cached = get_patched_session(session_key)
            if cached != node_id:
                # Patch the session to bind exec to this user's node.
                # req_id MUST be unique per call — the connection pool keys
                # pending-response futures by req_id and a duplicate ID
                # orphans the earlier future, hanging one caller 30s.
                try:
                    await pool.send_rpc(
                        user_id=owner_id,
                        req_id=f"bind-node-{uuid4()}",
                        method="sessions.patch",
                        # OpenClaw's sessions.patch takes `key` (see
                        # openclaw/src/gateway/server-methods/sessions.ts:1262).
                        # chat.send still uses `sessionKey` — that's a separate
                        # schema that didn't change.
                        params={
                            "key": session_key,
                            "execNode": node_id,
                            "execHost": "node",
                        },
                        ip=ip,
                        token=container["gateway_token"],
                    )
                    set_patched_session(session_key, node_id)
                    logger.info("Bound session %s to node %s", session_key, node_id[:16])
                except Exception:
                    logger.warning("Failed to bind session %s to node", session_key)

        # Plan 3 Task 4: card-3 (bedrock_claude) hard-stop when balance ≤ 0.
        # Cards 1+2 always pass through. We push a structured error event
        # back to the client and bail before forwarding to OpenClaw.
        # Use the per-user member id (not owner_id) so org-context chats
        # gate correctly — provider_choice + credit balance live on the
        # Clerk user row, not the org row. Codex P1 on PR #393.
        gate = await pool.gate_chat(user_id=user_id)
        if gate.get("blocked"):
            put_metric("chat.error", dimensions={"reason": gate.get("code", "blocked")})
            logger.info(
                "[%s] chat.send BLOCKED agent=%s code=%s",
                user_id,
                agent_id,
                gate.get("code"),
            )
            try:
                management_api.send_message(
                    connection_id,
                    {
                        "type": "error",
                        "code": gate.get("code", "blocked"),
                        "message": gate.get("message", "Chat blocked"),
                        "agent_id": agent_id,
                    },
                )
            except Exception:
                logger.warning("[%s] failed to deliver blocked-chat error event", user_id)
            return

        result = await pool.send_rpc(
            user_id=owner_id,
            req_id=req_id,
            method="chat.send",
            params={
                "sessionKey": session_key,
                "message": message,
                "idempotencyKey": str(uuid4()),
            },
            ip=ip,
            token=container["gateway_token"],
        )
        logger.info("[%s] chat.send ACK agent=%s result=%s", user_id, agent_id, result)
        # Streaming response events are forwarded by the connection pool's reader task

    except asyncio.TimeoutError:
        chat_err = "RPC timed out"
        put_metric("chat.error", dimensions={"reason": "timeout"})
        logger.error("[%s] chat.send TIMEOUT agent=%s", user_id, agent_id)
    except ConnectionError as e:
        chat_err = str(e)
        put_metric("chat.error", dimensions={"reason": "container_unreachable"})
        logger.error("[%s] chat.send CONNECT FAIL agent=%s: %s", user_id, agent_id, e)
    except RuntimeError as e:
        chat_err = str(e)
        put_metric("chat.error", dimensions={"reason": "gateway_error"})
        logger.error("[%s] chat.send GATEWAY ERROR agent=%s: %s", user_id, agent_id, e)
    except Exception as e:
        chat_err = str(e)
        put_metric("chat.error", dimensions={"reason": "unknown"})
        logger.error("[%s] chat.send FAIL agent=%s: %s", user_id, agent_id, e)
    else:
        return  # success — no error to report

    # All error branches fall through here to notify the client
    try:
        management_api.send_message(
            connection_id,
            {
                "type": "error",
                "agent_id": agent_id,
                "message": f"Failed to send message: {chat_err}",
            },
        )
    except Exception:
        pass
