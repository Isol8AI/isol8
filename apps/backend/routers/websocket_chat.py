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
from core.services.connection_service import ConnectionService, ConnectionServiceError
from core.services.management_api_client import ManagementApiClient

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

    logger.info("WebSocket connect: connection_id=%s, user_id=%s", x_connection_id, x_user_id)

    connection_service = await get_connection_service()
    connection_service.store_connection(
        connection_id=x_connection_id,
        user_id=x_user_id,
        org_id=x_org_id,
    )

    try:
        pool = get_gateway_pool()
        pool.add_frontend_connection(x_user_id, x_connection_id)
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
            pool = get_gateway_pool()
            pool.remove_frontend_connection(connection["user_id"], x_connection_id)
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
    msg_type = body.get("type")

    if msg_type == "ping":
        management_api = await get_management_api_client()
        management_api.send_message(x_connection_id, {"type": "pong"})
        return Response(status_code=200)

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

        # OpenClaw connect handshake — respond with hello-ok locally.
        # The control UI SPA sends this after receiving connect.challenge.
        # Auth is already handled by the Lambda authorizer, so we accept
        # any token and respond immediately.
        if method == "connect":
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

        background_tasks.add_task(
            _process_rpc_background,
            connection_id=x_connection_id,
            user_id=user_id,
            req_id=req_id,
            method=method,
            params=params,
        )
        return Response(status_code=200)

    if msg_type == "agent_chat":
        agent_id = body.get("agent_id")
        message = body.get("message")

        if not agent_id or not message:
            management_api = await get_management_api_client()
            management_api.send_message(
                x_connection_id,
                {"type": "error", "message": "Missing agent_id or message"},
            )
            return Response(status_code=200)

        background_tasks.add_task(
            _process_agent_chat_background,
            connection_id=x_connection_id,
            user_id=user_id,
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
    req_id: str,
    method: str,
    params: dict,
) -> None:
    """Process an OpenClaw RPC request via the gateway connection pool."""
    management_api = await get_management_api_client()

    try:
        ecs_manager = get_ecs_manager()
        container, ip = await ecs_manager.resolve_running_container(user_id)

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
            user_id=user_id,
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
    logger.debug(
        "Processing agent chat - connection_id=%s, user_id=%s, agent=%s",
        connection_id,
        user_id,
        agent_id,
    )

    management_api = await get_management_api_client()

    try:
        # Look up user's container and discover task IP
        ecs_manager = get_ecs_manager()
        container, ip = await ecs_manager.resolve_running_container(user_id)

        if not container:
            management_api.send_message(
                connection_id,
                {
                    "type": "error",
                    "message": "No container provisioned. Please subscribe to start chatting.",
                },
            )
            return

        if not ip:
            management_api.send_message(
                connection_id,
                {
                    "type": "error",
                    "message": "Your agent is starting up. Please try again in a moment.",
                },
            )
            return

        pool = get_gateway_pool()
        req_id = str(uuid4())

        # Session key format: agent:{agentId}:{sessionName}
        # OpenClaw resolves this to the agent's conversation session
        session_key = f"agent:{agent_id}:main"

        result = await pool.send_rpc(
            user_id=user_id,
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
        logger.debug("chat.send acked for agent %s: %s", agent_id, result)
        # Streaming response events are forwarded by the connection pool's reader task

    except Exception as e:
        logger.error("chat.send failed for agent %s: %s", agent_id, e)
        try:
            management_api.send_message(
                connection_id,
                {"type": "error", "message": f"Failed to send message: {e}"},
            )
        except Exception:
            pass
