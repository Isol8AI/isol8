"""
HTTP routes for API Gateway WebSocket integration.

API Gateway WebSocket converts WebSocket frames into HTTP POST requests:
- $connect  -> POST /ws/connect
- $disconnect -> POST /ws/disconnect
- $default (messages) -> POST /ws/message

Responses are pushed via Management API, not returned in HTTP response body.
"""

import asyncio
import logging
import secrets
import uuid as _uuid
from typing import Any, Dict, Optional
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.containers import get_ecs_manager, get_gateway_pool
from core.database import get_session_factory as db_get_session_factory
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


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get database session factory."""
    return db_get_session_factory()


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

    # Clean up town viewer subscription if active
    try:
        from routers.town import remove_town_viewer

        remove_town_viewer(x_connection_id)
    except Exception:
        pass

    # Clean up town agent connection if active — set agent to sleeping
    try:
        from core.services.town_agent_ws import get_town_agent_ws_manager

        ws_manager = get_town_agent_ws_manager()
        agent_conn = ws_manager.get_by_connection(x_connection_id)
        if agent_conn:
            ws_manager.unregister(x_connection_id)
            # Set agent to sleeping in DB since their WS is gone
            try:
                from core.database import get_session_factory
                from models.town import TownState
                from sqlalchemy import update
                from uuid import UUID

                async_session = get_session_factory()
                async with async_session() as session:
                    await session.execute(
                        update(TownState)
                        .where(TownState.agent_id == UUID(agent_conn.agent_id))
                        .values(
                            location_state="sleeping",
                            speed=0.0,
                            target_x=None,
                            target_y=None,
                            current_activity="sleeping",
                        )
                    )
                    await session.commit()
                logger.info("Agent %s set to sleeping on disconnect", agent_conn.agent_name)
            except Exception as e:
                logger.warning("Failed to set agent sleeping on disconnect: %s", e)
    except Exception:
        pass

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

    if msg_type == "town_agent_connect":
        token = body.get("token")
        agent_name = body.get("agent_name")
        management_api = await get_management_api_client()

        if not token or not agent_name:
            management_api.send_message(
                x_connection_id,
                {
                    "type": "town_event",
                    "event": "error",
                    "message": "Missing token or agent_name",
                },
            )
            return Response(status_code=200)

        session_factory = get_session_factory()
        async with session_factory() as session:
            from sqlalchemy import select
            from models.town import TownInstance, TownAgent, TownState

            result = await session.execute(
                select(TownInstance).where(
                    TownInstance.town_token == token,
                    TownInstance.is_active == True,  # noqa: E712
                )
            )
            instance = result.scalar_one_or_none()
            if not instance:
                management_api.send_message(
                    x_connection_id,
                    {"type": "town_event", "event": "error", "message": "Invalid token"},
                )
                return Response(status_code=200)

            result = await session.execute(
                select(TownAgent).where(
                    TownAgent.instance_id == instance.id,
                    TownAgent.agent_name == agent_name,
                    TownAgent.is_active == True,  # noqa: E712
                )
            )
            agent = result.scalar_one_or_none()
            if not agent:
                management_api.send_message(
                    x_connection_id,
                    {
                        "type": "town_event",
                        "event": "error",
                        "message": f"Agent '{agent_name}' not found",
                    },
                )
                return Response(status_code=200)

            # Get or create state
            result = await session.execute(select(TownState).where(TownState.agent_id == agent.id))
            state = result.scalar_one_or_none()
            if not state:
                from core.town_constants import TOWN_LOCATIONS

                home_loc = TOWN_LOCATIONS.get("apartment", {"x": 10.0, "y": 8.0})
                state = TownState(
                    agent_id=agent.id,
                    position_x=home_loc["x"],
                    position_y=home_loc["y"],
                    location_state="active",
                )
                session.add(state)
            else:
                state.location_state = "active"

            from datetime import datetime, timezone as tz

            state.last_heartbeat_at = datetime.now(tz.utc)
            instance.last_heartbeat_at = datetime.now(tz.utc)
            await session.commit()

            # Register in WS manager
            from core.services.town_agent_ws import get_town_agent_ws_manager

            ws_manager = get_town_agent_ws_manager()
            ws_manager.register(
                x_connection_id,
                instance.user_id,
                agent_name,
                str(agent.id),
                str(instance.id),
            )

            # Send initial state with apartment spots and town locations
            from core.apartment_constants import APARTMENT_SPOTS
            from core.town_constants import TOWN_LOCATIONS

            management_api.send_message(
                x_connection_id,
                {
                    "type": "town_event",
                    "event": "connected",
                    "agent": {
                        "name": agent.agent_name,
                        "display_name": agent.display_name,
                        "location": state.current_location,
                        "position": {"x": state.position_x, "y": state.position_y},
                        "location_state": state.location_state,
                        "location_context": getattr(state, "location_context", "apartment"),
                        "mood": state.mood,
                        "energy": state.energy,
                        "activity": state.current_activity,
                    },
                    "apartment": {
                        "spots": {
                            spot_id: {"room": spot["room"], "label": spot["label"]}
                            for spot_id, spot in APARTMENT_SPOTS.items()
                        }
                    },
                    "town": {"locations": {loc_id: {"label": loc["label"]} for loc_id, loc in TOWN_LOCATIONS.items()}},
                },
            )

        return Response(status_code=200)

    if msg_type == "town_agent_act":
        from core.services.town_agent_ws import get_town_agent_ws_manager

        ws_manager = get_town_agent_ws_manager()
        agent_conn = ws_manager.get_by_connection(x_connection_id)
        management_api = await get_management_api_client()

        if not agent_conn:
            management_api.send_message(
                x_connection_id,
                {
                    "type": "town_event",
                    "event": "error",
                    "message": "Not connected as town agent",
                },
            )
            return Response(status_code=200)

        action = body.get("action")
        session_factory = get_session_factory()
        async with session_factory() as session:
            from sqlalchemy import select
            from models.town import TownState

            result = await session.execute(
                select(TownState).where(TownState.agent_id == _uuid.UUID(agent_conn.agent_id))
            )
            state = result.scalar_one_or_none()
            if not state:
                return Response(status_code=200)

            if action == "move":
                from core.town_constants import TOWN_LOCATIONS
                from core.apartment_constants import APARTMENT_SPOTS, RESIDENTIAL_TOWN_COORDS

                dest = body.get("destination")
                location_context = state.location_context or "apartment"

                # Get simulation reference for pending destinations and path clearing
                import main as _main_module

                sim = _main_module._town_simulation

                if dest in APARTMENT_SPOTS:
                    if location_context == "apartment":
                        # Check occupancy and fallback to available spot in same room
                        final_dest = dest
                        spot = APARTMENT_SPOTS[dest]

                        from core.services.town_service import TownService

                        town_svc = TownService(session)
                        all_states = await town_svc.get_town_state()
                        occupied_spots = {
                            s["current_location"]
                            for s in all_states
                            if s["agent_id"] != state.agent_id
                            and s.get("location_context") == "apartment"
                            and s.get("current_location")
                        }

                        if dest in occupied_spots:
                            target_room = spot.get("room")
                            for spot_id, spot_data in APARTMENT_SPOTS.items():
                                if (
                                    spot_data.get("room") == target_room
                                    and spot_id not in occupied_spots
                                    and spot_id != dest
                                ):
                                    final_dest = spot_id
                                    spot = APARTMENT_SPOTS[final_dest]
                                    break

                        state.target_x = float(spot["x"])
                        state.target_y = float(spot["y"])
                        state.target_location = final_dest
                    else:
                        # In town -> walk to residential first
                        state.target_x = RESIDENTIAL_TOWN_COORDS["x"]
                        state.target_y = RESIDENTIAL_TOWN_COORDS["y"]
                        state.target_location = "home"
                        if sim:
                            sim._pending_destinations[state.agent_id] = dest
                    state.current_activity = "walking"
                    state.location_state = "active"
                    state.speed = 0.6
                elif dest in TOWN_LOCATIONS:
                    if location_context == "town":
                        loc = TOWN_LOCATIONS[dest]
                        state.target_x = float(loc["x"])
                        state.target_y = float(loc["y"])
                        state.target_location = dest
                    else:
                        # In apartment -> walk to exit first
                        exit_spot = APARTMENT_SPOTS["exit"]
                        state.target_x = float(exit_spot["x"])
                        state.target_y = float(exit_spot["y"])
                        state.target_location = "exit"
                        if sim:
                            sim._pending_destinations[state.agent_id] = dest
                    state.current_activity = "walking"
                    state.location_state = "active"
                    state.speed = 0.6
                else:
                    management_api.send_message(
                        x_connection_id,
                        {
                            "type": "town_event",
                            "event": "error",
                            "message": f"Unknown destination: {dest}",
                        },
                    )
                    return Response(status_code=200)

                # Clear stale A* path so simulation recomputes
                if sim:
                    sim._agent_paths.pop(state.agent_id, None)
            elif action == "idle":
                state.current_activity = body.get("activity", "idle")
                state.target_x = None
                state.target_y = None
                state.speed = 0

            elif action == "chat":
                # Initiate a conversation with another agent
                target_name = body.get("target")
                chat_message = body.get("message", "")

                if not target_name:
                    management_api.send_message(
                        x_connection_id,
                        {"type": "town_event", "event": "error", "message": "Missing target agent name"},
                    )
                    return Response(status_code=200)

                # Cannot chat with self
                if target_name == agent_conn.agent_name:
                    management_api.send_message(
                        x_connection_id,
                        {"type": "town_event", "event": "error", "message": "Cannot chat with yourself"},
                    )
                    return Response(status_code=200)

                # Check initiator not already in conversation
                if state.current_conversation_id is not None:
                    management_api.send_message(
                        x_connection_id,
                        {"type": "town_event", "event": "error", "message": "Already in a conversation"},
                    )
                    return Response(status_code=200)

                # Look up target connection
                target_conn_id = ws_manager.get_agent_connection_id(target_name)
                if not target_conn_id:
                    management_api.send_message(
                        x_connection_id,
                        {"type": "town_event", "event": "error", "message": f"Agent '{target_name}' is not connected"},
                    )
                    return Response(status_code=200)

                target_agent_conn = ws_manager.get_by_connection(target_conn_id)

                # Look up target's TownState to check if busy
                from models.town import TownConversation

                target_state_result = await session.execute(
                    select(TownState).where(TownState.agent_id == _uuid.UUID(target_agent_conn.agent_id))
                )
                target_state = target_state_result.scalar_one_or_none()
                if not target_state:
                    management_api.send_message(
                        x_connection_id,
                        {"type": "town_event", "event": "error", "message": f"Agent '{target_name}' state not found"},
                    )
                    return Response(status_code=200)

                if target_state.current_conversation_id is not None:
                    management_api.send_message(
                        x_connection_id,
                        {"type": "town_event", "event": "busy", "agent": target_name},
                    )
                    return Response(status_code=200)

                # Create conversation
                from datetime import datetime, timezone as tz

                initiator_id = _uuid.UUID(agent_conn.agent_id)
                target_id = _uuid.UUID(target_agent_conn.agent_id)

                conversation = TownConversation(
                    participant_a_id=initiator_id,
                    participant_b_id=target_id,
                    location=state.current_location,
                    status="active",
                    turn_count=0,
                    public_log=[],
                )
                session.add(conversation)
                await session.flush()  # get conversation.id

                # Update both agents' states
                state.current_activity = "chatting"
                state.current_conversation_id = conversation.id
                target_state.current_activity = "chatting"
                target_state.current_conversation_id = conversation.id

                # Push invite to target
                management_api.send_message(
                    target_conn_id,
                    {
                        "type": "town_event",
                        "event": "conversation_invite",
                        "from": agent_conn.agent_name,
                        "conv_id": str(conversation.id),
                        "message": chat_message,
                    },
                )

                # Push to viewers: conversation started
                try:
                    from routers.town import _push_to_viewers

                    _push_to_viewers(
                        {
                            "type": "town_event",
                            "event": "conversation_started",
                            "conv_id": str(conversation.id),
                            "participants": [agent_conn.agent_name, target_name],
                            "initiator": agent_conn.agent_name,
                            "message": chat_message,
                        }
                    )
                except Exception:
                    pass

            elif action == "say":
                # Send a message in an ongoing conversation
                conv_id_str = body.get("conv_id")
                say_message = body.get("message", "")

                if not conv_id_str:
                    management_api.send_message(
                        x_connection_id,
                        {"type": "town_event", "event": "error", "message": "Missing conv_id"},
                    )
                    return Response(status_code=200)

                from models.town import TownConversation

                conv_result = await session.execute(
                    select(TownConversation).where(TownConversation.id == _uuid.UUID(conv_id_str))
                )
                conversation = conv_result.scalar_one_or_none()
                if not conversation:
                    management_api.send_message(
                        x_connection_id,
                        {"type": "town_event", "event": "error", "message": "Conversation not found"},
                    )
                    return Response(status_code=200)

                if conversation.status != "active":
                    management_api.send_message(
                        x_connection_id,
                        {"type": "town_event", "event": "error", "message": "Conversation is not active"},
                    )
                    return Response(status_code=200)

                # Verify this agent is a participant
                agent_uuid = _uuid.UUID(agent_conn.agent_id)
                if agent_uuid != conversation.participant_a_id and agent_uuid != conversation.participant_b_id:
                    management_api.send_message(
                        x_connection_id,
                        {"type": "town_event", "event": "error", "message": "Not a participant in this conversation"},
                    )
                    return Response(status_code=200)

                # Append to public_log
                log_entry = {"speaker": agent_conn.agent_name, "text": say_message}
                current_log = list(conversation.public_log or [])
                current_log.append(log_entry)
                conversation.public_log = current_log
                conversation.turn_count = len(current_log)

                # Find partner
                if agent_uuid == conversation.participant_a_id:
                    partner_id = conversation.participant_b_id
                else:
                    partner_id = conversation.participant_a_id

                # Look up partner's connection
                partner_conn_id = None
                for ac in ws_manager.connected_agents():
                    if ac.agent_id == str(partner_id):
                        partner_conn_id = ac.connection_id
                        break

                # Push message to partner
                if partner_conn_id:
                    management_api.send_message(
                        partner_conn_id,
                        {
                            "type": "town_event",
                            "event": "conversation_message",
                            "from": agent_conn.agent_name,
                            "text": say_message,
                            "conv_id": conv_id_str,
                            "turn": conversation.turn_count,
                        },
                    )

                # Push to viewers: speech bubble
                try:
                    from routers.town import _push_to_viewers

                    _push_to_viewers(
                        {
                            "type": "town_event",
                            "event": "speech_bubble",
                            "conv_id": conv_id_str,
                            "speaker": agent_conn.agent_name,
                            "text": say_message,
                            "turn": conversation.turn_count,
                        }
                    )
                except Exception:
                    pass

                # Auto-end conversation if max turns reached
                MAX_CONVERSATION_TURNS = 10
                if conversation.turn_count >= MAX_CONVERSATION_TURNS:
                    from datetime import datetime, timezone as tz

                    conversation.status = "ended"
                    conversation.ended_at = datetime.now(tz.utc)

                    # Clear both participants' conversation state
                    state.current_conversation_id = None
                    state.current_activity = "idle"

                    partner_state_result = await session.execute(
                        select(TownState).where(TownState.agent_id == partner_id)
                    )
                    partner_state = partner_state_result.scalar_one_or_none()
                    if partner_state:
                        partner_state.current_conversation_id = None
                        partner_state.current_activity = "idle"

                    # Update relationship
                    from core.services.town_service import TownService

                    town_svc = TownService(session)
                    rel, _ = await town_svc.get_or_create_relationship(
                        conversation.participant_a_id, conversation.participant_b_id
                    )
                    await town_svc.update_relationship(rel.id, affinity_delta=1)

                    # Notify partner of auto-end
                    if partner_conn_id:
                        management_api.send_message(
                            partner_conn_id,
                            {
                                "type": "town_event",
                                "event": "conversation_ended",
                                "conv_id": conv_id_str,
                                "reason": "max_turns",
                            },
                        )

                    # Notify viewers
                    try:
                        from routers.town import _push_to_viewers

                        _push_to_viewers(
                            {
                                "type": "town_event",
                                "event": "conversation_ended",
                                "conv_id": conv_id_str,
                                "reason": "max_turns",
                            }
                        )
                    except Exception:
                        pass

            elif action == "end_conversation":
                # End a conversation
                conv_id_str = body.get("conv_id")

                if not conv_id_str:
                    management_api.send_message(
                        x_connection_id,
                        {"type": "town_event", "event": "error", "message": "Missing conv_id"},
                    )
                    return Response(status_code=200)

                from models.town import TownConversation

                conv_result = await session.execute(
                    select(TownConversation).where(TownConversation.id == _uuid.UUID(conv_id_str))
                )
                conversation = conv_result.scalar_one_or_none()
                if not conversation:
                    management_api.send_message(
                        x_connection_id,
                        {"type": "town_event", "event": "error", "message": "Conversation not found"},
                    )
                    return Response(status_code=200)

                # Verify this agent is a participant
                agent_uuid = _uuid.UUID(agent_conn.agent_id)
                if agent_uuid != conversation.participant_a_id and agent_uuid != conversation.participant_b_id:
                    management_api.send_message(
                        x_connection_id,
                        {"type": "town_event", "event": "error", "message": "Not a participant in this conversation"},
                    )
                    return Response(status_code=200)

                from datetime import datetime, timezone as tz

                # End the conversation
                conversation.status = "ended"
                conversation.ended_at = datetime.now(tz.utc)

                # Clear both participants' conversation state
                state.current_conversation_id = None
                state.current_activity = "idle"

                # Find partner
                if agent_uuid == conversation.participant_a_id:
                    partner_id = conversation.participant_b_id
                else:
                    partner_id = conversation.participant_a_id

                partner_state_result = await session.execute(select(TownState).where(TownState.agent_id == partner_id))
                partner_state = partner_state_result.scalar_one_or_none()
                if partner_state:
                    partner_state.current_conversation_id = None
                    partner_state.current_activity = "idle"

                # Update relationship
                from core.services.town_service import TownService

                town_svc = TownService(session)
                rel, _ = await town_svc.get_or_create_relationship(
                    conversation.participant_a_id, conversation.participant_b_id
                )
                await town_svc.update_relationship(rel.id, affinity_delta=1)

                # Push to partner
                partner_conn_id = None
                for ac in ws_manager.connected_agents():
                    if ac.agent_id == str(partner_id):
                        partner_conn_id = ac.connection_id
                        break

                if partner_conn_id:
                    management_api.send_message(
                        partner_conn_id,
                        {
                            "type": "town_event",
                            "event": "conversation_ended",
                            "conv_id": conv_id_str,
                        },
                    )

                # Push to viewers
                try:
                    from routers.town import _push_to_viewers

                    _push_to_viewers(
                        {
                            "type": "town_event",
                            "event": "conversation_ended",
                            "conv_id": conv_id_str,
                        }
                    )
                except Exception:
                    pass

            from datetime import datetime, timezone as tz

            state.last_decision_at = datetime.now(tz.utc)
            await session.commit()

        management_api.send_message(
            x_connection_id,
            {"type": "town_event", "event": "act_ok", "action": action},
        )
        return Response(status_code=200)

    if msg_type == "town_agent_sleep":
        from core.services.town_agent_ws import get_town_agent_ws_manager

        ws_manager = get_town_agent_ws_manager()
        agent_conn = ws_manager.get_by_connection(x_connection_id)
        management_api = await get_management_api_client()

        if not agent_conn:
            return Response(status_code=200)

        session_factory = get_session_factory()
        async with session_factory() as session:
            from sqlalchemy import select
            from models.town import TownState
            from core.town_constants import TOWN_LOCATIONS

            result = await session.execute(
                select(TownState).where(TownState.agent_id == _uuid.UUID(agent_conn.agent_id))
            )
            state = result.scalar_one_or_none()
            if state:
                from core.services.town_simulation import AGENT_SPEED

                home_loc = TOWN_LOCATIONS.get("residence", {"x": 69.0, "y": 25.0})
                state.target_x = float(home_loc["x"])
                state.target_y = float(home_loc["y"])
                state.current_activity = "going_home"
                state.location_state = "going_home"
                state.speed = AGENT_SPEED

                # Parse optional wake alarm from the message body
                wake_time_str = body.get("wake_time")
                wake_tz_str = body.get("timezone", "UTC")
                if wake_time_str:
                    import zoneinfo
                    from datetime import datetime, timedelta, timezone

                    try:
                        tz_info = zoneinfo.ZoneInfo(wake_tz_str)
                        now_local = datetime.now(tz_info)
                        hour, minute = map(int, wake_time_str.split(":"))
                        wake_local = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
                        if wake_local <= now_local:
                            wake_local += timedelta(days=1)
                        state.wake_at = wake_local.astimezone(timezone.utc)
                        state.wake_timezone = wake_tz_str
                    except Exception as e:
                        logger.warning(f"Failed to parse wake time: {e}")

                await session.commit()

        ws_manager.unregister(x_connection_id)
        management_api.send_message(
            x_connection_id,
            {"type": "town_event", "event": "sleep_ok"},
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

    except RuntimeError as e:
        # RuntimeError comes from OpenClaw rejecting the RPC — forward full error object.
        # connection_pool serializes the gateway error dict as JSON in the message.
        logger.warning("RPC %s rejected for user %s: %s", method, user_id, e)
        try:
            import json as _json

            try:
                error_obj = _json.loads(str(e))
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
            token=container.gateway_token,
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
