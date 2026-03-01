"""
HTTP routes for API Gateway WebSocket integration.

API Gateway WebSocket converts WebSocket frames into HTTP POST requests:
- $connect  -> POST /ws/connect
- $disconnect -> POST /ws/disconnect
- $default (messages) -> POST /ws/message

Responses are pushed via Management API, not returned in HTTP response body.
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.containers import get_ecs_manager, get_gateway_pool, GatewayHttpClient, GatewayRequestError
from core.containers.ecs_manager import GATEWAY_PORT
from core.database import get_session_factory as db_get_session_factory
from core.services.connection_service import ConnectionService, ConnectionServiceError
from core.services.management_api_client import ManagementApiClient, ManagementApiClientError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


# Singleton instances (created lazily)
_connection_service: Optional[ConnectionService] = None
_management_api_client: Optional[ManagementApiClient] = None


def get_connection_service() -> ConnectionService:
    """Get or create ConnectionService singleton."""
    global _connection_service
    if _connection_service is None:
        _connection_service = ConnectionService()
    return _connection_service


def get_management_api_client() -> ManagementApiClient:
    """Get or create ManagementApiClient singleton."""
    global _management_api_client
    if _management_api_client is None:
        _management_api_client = ManagementApiClient()
    return _management_api_client


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get database session factory."""
    return db_get_session_factory()


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
    x_connection_id: Optional[str] = Header(None, alias="x-connection-id"),
    x_user_id: Optional[str] = Header(None, alias="x-user-id"),
    x_org_id: Optional[str] = Header(None, alias="x-org-id"),
) -> Response:
    if not x_connection_id:
        raise HTTPException(status_code=400, detail="Missing x-connection-id header")
    if not x_user_id:
        raise HTTPException(status_code=401, detail="Missing x-user-id header")

    logger.info("WebSocket connect: connection_id=%s, user_id=%s", x_connection_id, x_user_id)

    connection_service = get_connection_service()
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
        connection_service = get_connection_service()
        connection = connection_service.get_connection(x_connection_id)
        if connection:
            pool = get_gateway_pool()
            pool.remove_frontend_connection(connection["user_id"], x_connection_id)
    except Exception as e:
        logger.warning("Failed to unregister frontend connection from pool: %s", e)

    # Clean up town viewer subscription if active
    try:
        from routers.town import remove_town_viewer

        remove_town_viewer(x_connection_id)
    except Exception:
        pass

    try:
        connection_service = get_connection_service()
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

    connection_service = get_connection_service()
    connection = connection_service.get_connection(x_connection_id)

    if not connection:
        raise HTTPException(status_code=401, detail="Unknown connection")

    user_id = connection["user_id"]
    msg_type = body.get("type")

    if msg_type == "ping":
        management_api = get_management_api_client()
        management_api.send_message(x_connection_id, {"type": "pong"})
        return Response(status_code=200)

    if msg_type == "pong":
        return Response(status_code=200)

    if msg_type == "town_subscribe":
        from routers.town import add_town_viewer

        add_town_viewer(x_connection_id)
        return Response(status_code=200)

    if msg_type == "town_unsubscribe":
        from routers.town import remove_town_viewer

        remove_town_viewer(x_connection_id)
        return Response(status_code=200)

    if msg_type == "req":
        req_id = body.get("id")
        method = body.get("method")
        params = body.get("params", {})

        if not req_id or not method:
            management_api = get_management_api_client()
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
        agent_name = body.get("agent_name")
        message = body.get("message")

        if not agent_name or not message:
            management_api = get_management_api_client()
            management_api.send_message(
                x_connection_id,
                {"type": "error", "message": "Missing agent_name or message"},
            )
            return Response(status_code=200)

        background_tasks.add_task(
            _process_agent_chat_background,
            connection_id=x_connection_id,
            user_id=user_id,
            agent_name=agent_name,
            message=message,
        )
        return Response(status_code=200)

    # Unknown message type
    management_api = get_management_api_client()
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
    management_api = get_management_api_client()

    try:
        ecs_manager = get_ecs_manager()
        session_factory = get_session_factory()
        async with session_factory() as db:
            container, ip = await ecs_manager.resolve_running_container(user_id, db)

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
            token=container.gateway_token,
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

    except Exception as e:
        logger.error("RPC %s failed for user %s: %s", method, user_id, e)
        try:
            management_api.send_message(
                connection_id,
                {
                    "type": "res",
                    "id": req_id,
                    "ok": False,
                    "error": {"message": "Internal error processing request."},
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
    agent_name: str,
    message: str,
) -> None:
    """
    Process agent chat message in background task with streaming.

    Routes to the user's dedicated OpenClaw container. OpenClaw manages
    agents internally — agent_name is passed directly as x-openclaw-agent-id
    (e.g. "main"). Users without a container receive an error message.
    """
    logger.debug(
        "Processing agent chat - connection_id=%s, user_id=%s, agent=%s",
        connection_id,
        user_id,
        agent_name,
    )

    management_api = get_management_api_client()

    try:
        # Look up user's container and discover task IP
        ecs_manager = get_ecs_manager()
        session_factory = get_session_factory()
        async with session_factory() as db:
            container, ip = await ecs_manager.resolve_running_container(user_id, db)

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

        gateway_client = GatewayHttpClient(
            base_url=f"http://{ip}:{GATEWAY_PORT}",
            token=container.gateway_token,
        )
        logger.debug("Routing to user container at %s:%d", ip, GATEWAY_PORT)

        # Stream response — pass agent_name directly to OpenClaw
        chunk_count = 0

        for chunk in gateway_client.chat_stream(
            message=message,
            agent_id=agent_name,
        ):
            if chunk is None:
                management_api.send_message(connection_id, {"type": "heartbeat"})
                continue

            chunk_count += 1
            push_ok = management_api.send_message(
                connection_id,
                {"type": "chunk", "content": chunk},
            )
            if not push_ok:
                logger.warning("Connection %s gone during agent streaming", connection_id)
                return

        logger.debug(
            "Agent stream complete: connection_id=%s, agent=%s, chunks=%d",
            connection_id,
            agent_name,
            chunk_count,
        )
        management_api.send_message(connection_id, {"type": "done"})

    except GatewayRequestError as e:
        logger.error("Gateway error for agent %s: %s", agent_name, e)
        management_api.send_message(
            connection_id,
            {"type": "error", "message": f"Agent processing error: {e}"},
        )
    except ManagementApiClientError as e:
        logger.error("Management API error for connection %s: %s", connection_id, e)
    except Exception as e:
        logger.exception("Unexpected error processing agent chat for connection %s: %s", connection_id, e)
        try:
            management_api.send_message(
                connection_id,
                {"type": "error", "message": "Internal error during processing"},
            )
        except Exception:
            pass
