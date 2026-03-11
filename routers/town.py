"""GooseTown API endpoints.

Serves two sets of endpoints:
1. Isol8-native endpoints (apartment, instance, registration) — authenticated
2. AI Town-compatible endpoints (status, state, descriptions, etc.) — public,
   return plain dicts matching AI Town's TypeScript class constructors
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import AuthContext, get_current_user
from core.database import get_db
from core.services.management_api_client import ManagementApiClient, ManagementApiClientError
from core.services.town_service import TownService
from models.town import TownAgent, TownState
from schemas.town import (
    ApartmentAgentState,
    ApartmentResponse,
    TownConversationResponse,
    TownConversationsListResponse,
    ConversationTurn,
)

logger = logging.getLogger(__name__)
router = APIRouter()

_TOWN_WS_URL = os.environ.get("TOWN_WS_URL", "wss://ws-dev.isol8.co")
_TOWN_API_URL = os.environ.get("TOWN_API_URL", "https://api-dev.isol8.co/api/v1")

# Strong references to background sprite tasks to prevent GC
_background_sprite_tasks: set = set()


# ---------------------------------------------------------------------------
# Token auth dependency for external OpenClaw agents
# ---------------------------------------------------------------------------


async def get_town_token_user(
    authorization: str = Header(..., alias="Authorization"),
    db: AsyncSession = Depends(get_db),
) -> tuple:
    """Validate a town_token from Authorization: Bearer <token>.
    Returns (user_id, token) or raises 401.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = authorization[7:]

    service = TownService(db)
    instance = await service.get_instance_by_token(token)
    if not instance or not instance.is_active:
        raise HTTPException(status_code=401, detail="Invalid or expired town token")
    return instance.user_id, token


# ---------------------------------------------------------------------------
# Map data cache (loaded once from gentle_map.json)
# ---------------------------------------------------------------------------

_map_data: Optional[dict] = None


def _load_map_data() -> dict:
    """Load and cache the tilemap data, remapping to AI Town field names."""
    global _map_data
    if _map_data is not None:
        return _map_data

    map_path = Path(__file__).parent.parent / "data" / "city_map.json"
    if not map_path.exists():
        logger.warning("city_map.json not found, using empty map")
        _map_data = {
            "width": 64,
            "height": 48,
            "tileSetUrl": "/ai-town/assets/gentle-obj.png",
            "tileSetDimX": 1440,
            "tileSetDimY": 1024,
            "tileDim": 32,
            "bgTiles": [],
            "objectTiles": [],
            "animatedSprites": [],
        }
        return _map_data

    with open(map_path) as f:
        raw = json.load(f)

    _map_data = {
        "width": raw["mapwidth"],
        "height": raw["mapheight"],
        "tileSetUrl": raw["tilesetpath"],
        "tileSetDimX": raw["tilesetpxw"],
        "tileSetDimY": raw["tilesetpxh"],
        "tileDim": raw["tiledim"],
        "bgTiles": raw["bgtiles"],
        "objectTiles": raw["objmap"],
        "animatedSprites": raw["animatedsprites"],
    }
    return _map_data


# Persistent world ID (single world for now)
WORLD_ID = "world_default"
ENGINE_ID = "engine_default"

# ---------------------------------------------------------------------------
# Real-time state push via API Gateway WebSocket
# ---------------------------------------------------------------------------
# Town viewers subscribe via the shared API Gateway WebSocket (same one used
# for chat).  When game state changes (join/leave/move), we push the combined
# state to every viewer in a single message — giving the frontend the same
# atomic update guarantee that Convex subscriptions provide.
# ---------------------------------------------------------------------------

_town_viewer_connections: set[str] = set()

# Lazy singleton — created on first push.  Returns None in local dev where
# WS_MANAGEMENT_API_URL is not set (no-op push).
_town_mgmt_api: Optional[ManagementApiClient] = None
_town_mgmt_api_failed: bool = False


def _get_town_mgmt_api() -> Optional[ManagementApiClient]:
    global _town_mgmt_api, _town_mgmt_api_failed
    if _town_mgmt_api is not None:
        return _town_mgmt_api
    if _town_mgmt_api_failed:
        return None
    try:
        _town_mgmt_api = ManagementApiClient()
        return _town_mgmt_api
    except ManagementApiClientError:
        # No WS_MANAGEMENT_API_URL — local dev, push is a no-op
        _town_mgmt_api_failed = True
        logger.info("ManagementApiClient unavailable — town WS push disabled")
        return None


async def _build_ws_message_async() -> dict:
    """Build the combined state payload for WebSocket clients (async, reads DB)."""
    from core.database import async_session_factory

    async with async_session_factory() as db:
        state = await _build_ai_town_state(db)

    world_map = _load_map_data()
    return {
        "type": "town_state",
        "worldState": {"world": state["world"], "engine": state["engine"]},
        "gameDescriptions": {
            "worldMap": world_map,
            "playerDescriptions": state["playerDescriptions"],
            "agentDescriptions": state["agentDescriptions"],
        },
        "speechBubbles": state.get("speechBubbles", []),
    }


def _build_ws_message() -> dict:
    """Build the combined state payload for WebSocket clients (sync fallback).

    Uses default state. Prefer _build_ws_message_async() for DB-backed state.
    """
    state = _build_default_state()
    world_map = _load_map_data()
    return {
        "type": "town_state",
        "worldState": {"world": state["world"], "engine": state["engine"]},
        "gameDescriptions": {
            "worldMap": world_map,
            "playerDescriptions": state["playerDescriptions"],
            "agentDescriptions": state["agentDescriptions"],
        },
        "speechBubbles": [],
    }


def _notify_state_changed():
    """Push updated state to all connected town viewers via API Gateway.

    Called after any mutation that changes game state (join, leave, moveTo).
    Also called by TownSimulation after each tick.
    Dead connections (GoneException) are silently removed.
    """
    if not _town_viewer_connections:
        return
    mgmt = _get_town_mgmt_api()
    if mgmt is None:
        return

    # Try async DB-backed state; fall back to defaults on failure
    import asyncio

    try:
        loop = asyncio.get_running_loop()
        # Schedule async message build as a fire-and-forget task
        loop.create_task(_async_notify_viewers())
        return
    except RuntimeError:
        # No event loop — skip push, REST polling will fill in
        pass


async def _async_notify_viewers():
    """Async helper: build state from DB and push to all viewers."""
    mgmt = _get_town_mgmt_api()
    if mgmt is None:
        return
    try:
        message = await _build_ws_message_async()
    except Exception:
        logger.debug("Failed to build async WS message, skipping push")
        return
    _push_to_viewers(message)


def _push_to_viewers(message: dict):
    """Send a message dict to all connected town viewers."""
    mgmt = _get_town_mgmt_api()
    if mgmt is None:
        return
    dead: list[str] = []
    for conn_id in list(_town_viewer_connections):
        try:
            if not mgmt.send_message(conn_id, message):
                dead.append(conn_id)
        except ManagementApiClientError:
            dead.append(conn_id)
    for conn_id in dead:
        _town_viewer_connections.discard(conn_id)


def add_town_viewer(connection_id: str):
    """Register a WebSocket connection as a town viewer and push initial state."""
    import asyncio

    _town_viewer_connections.add(connection_id)
    mgmt = _get_town_mgmt_api()
    if mgmt is None:
        return

    async def _send_initial():
        try:
            msg = await _build_ws_message_async()
        except Exception:
            logger.debug("Failed to build initial WS message, skipping")
            return
        try:
            mgmt.send_message(connection_id, msg)
        except ManagementApiClientError:
            _town_viewer_connections.discard(connection_id)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_send_initial())
    except RuntimeError:
        # No event loop — skip initial push, REST polling will fill in
        pass


def remove_town_viewer(connection_id: str):
    """Unregister a WebSocket connection from town updates."""
    _town_viewer_connections.discard(connection_id)


# ---------------------------------------------------------------------------
# Helper: build AI Town-format state from DB
# ---------------------------------------------------------------------------


def _build_default_state() -> dict:
    """Build empty AI Town state when no agents exist.

    Returns a dict matching SerializedWorld + engine status with no players.
    """
    now_ms = int(time.time() * 1000)
    return {
        "world": {
            "nextId": 0,
            "players": [],
            "agents": [],
            "conversations": [],
        },
        "engine": {
            "currentTime": now_ms,
            "lastStepTs": now_ms - 16,
        },
        "playerDescriptions": [],
        "agentDescriptions": [],
        "speechBubbles": [],
    }


async def _build_ai_town_state(db: AsyncSession) -> dict:
    """Build AI Town-compatible world state from the database.

    Only includes agents registered via the per-agent registration flow.
    """
    try:
        service = TownService(db)
        db_states = await service.get_town_state()
    except Exception:
        logger.debug("Town tables not available, using defaults")
        return _build_default_state()

    if not db_states:
        return _build_default_state()

    # Only include agents in the town coordinate space
    db_states = [s for s in db_states if s.get("location_context", "apartment") == "town"]
    if not db_states:
        return _build_default_state()

    now_ms = int(time.time() * 1000)
    players = []
    agents = []
    player_descriptions = []
    agent_descriptions = []

    for i, s in enumerate(db_states):
        player_id = f"p:{i}"
        agent_id = f"a:{i}"

        # Use facing from DB state, or compute from target
        facing_x = s.get("facing_x", 0.0)
        facing_y = s.get("facing_y", 1.0)
        speed = s.get("speed", 0.0)

        players.append(
            {
                "id": player_id,
                "position": {"x": s["position_x"], "y": s["position_y"]},
                "facing": {"dx": facing_x, "dy": facing_y},
                "speed": speed,
                "lastInput": now_ms,
            }
        )

        agents.append(
            {
                "id": agent_id,
                "playerId": player_id,
            }
        )

        player_descriptions.append(
            {
                "playerId": player_id,
                "name": s.get("display_name", s.get("agent_name", "Unknown")),
                "description": s.get("personality_summary", ""),
                "character": s.get("character"),
                "spriteUrl": s.get("sprite_url"),
            }
        )

        agent_descriptions.append(
            {
                "agentId": agent_id,
                "identity": s.get("personality_summary", ""),
                "plan": "",
            }
        )

    # Speech bubbles from recent conversations
    try:
        speech_bubbles = await service.get_recent_speech(since_seconds=10.0)
    except Exception:
        speech_bubbles = []

    return {
        "world": {
            "nextId": len(db_states),
            "players": players,
            "agents": agents,
            "conversations": [],
        },
        "engine": {
            "currentTime": now_ms,
            "lastStepTs": now_ms - 16,
        },
        "playerDescriptions": player_descriptions,
        "agentDescriptions": agent_descriptions,
        "speechBubbles": speech_bubbles,
    }


# ===========================================================================
# AI Town-compatible endpoints (public, no auth required)
# ===========================================================================


@router.get("/status")
async def get_world_status():
    """Return default world status. Game.tsx calls this first."""
    now_ms = int(time.time() * 1000)
    return {
        "worldId": WORLD_ID,
        "engineId": ENGINE_ID,
        "status": "running",
        "lastViewed": now_ms,
        "isDefault": True,
    }


@router.get("/state")
async def get_world_state(
    worldId: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Return world state in AI Town format.

    Used by useServerGame + useHistoricalTime for PixiJS rendering.
    """
    state = await _build_ai_town_state(db)
    return {
        "world": state["world"],
        "engine": state["engine"],
        "speechBubbles": state.get("speechBubbles", []),
    }


@router.get("/descriptions")
async def get_game_descriptions(
    worldId: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Return map data + agent/player descriptions.

    Used by useServerGame to construct WorldMap, PlayerDescription,
    AgentDescription objects.
    """
    state = await _build_ai_town_state(db)
    world_map = _load_map_data()

    return {
        "worldMap": world_map,
        "playerDescriptions": state["playerDescriptions"],
        "agentDescriptions": state["agentDescriptions"],
    }


# ===========================================================================
# Agent registration endpoints (town_token auth)
# ===========================================================================


class AgentRegisterRequest(BaseModel):
    agent_name: str = Field(..., min_length=1, max_length=50, pattern="^[a-zA-Z0-9_-]+$")
    display_name: str = Field(..., min_length=1, max_length=100)
    personality: str = Field("", max_length=500)
    appearance: str = Field("", max_length=500)
    traits: str = Field("", max_length=200)


@router.post("/agent/register")
async def register_agent(
    request: AgentRegisterRequest = Body(...),
    token_info: tuple = Depends(get_town_token_user),
    db: AsyncSession = Depends(get_db),
):
    """Register a new agent in GooseTown. Authenticated via town_token."""
    from core.apartment_constants import APARTMENT_SPOTS

    user_id, token = token_info

    service = TownService(db)
    instance = await service.get_active_instance(user_id)
    if not instance:
        raise HTTPException(400, "No active instance")

    existing = await service.get_agent_by_name(user_id, request.agent_name)
    if existing:
        raise HTTPException(400, f"Agent '{request.agent_name}' already registered")

    # Spawn at apartment bed
    spawn = APARTMENT_SPOTS["bed_1"]

    agent = TownAgent(
        user_id=user_id,
        agent_name=request.agent_name,
        display_name=request.display_name,
        personality_summary=request.personality[:200] if request.personality else None,
        traits=request.traits,
        home_location="residence",
        instance_id=instance.id,
    )
    db.add(agent)
    await db.flush()

    state = TownState(
        agent_id=agent.id,
        position_x=spawn["x"],
        position_y=spawn["y"],
        current_location="bedroom",
        location_context="apartment",
        location_state="active",
        current_activity="idle",
    )
    db.add(state)
    await db.commit()

    _notify_state_changed()

    # Trigger PixelLab sprite generation in background
    logger.info(
        f"Sprite check: appearance={bool(request.appearance)}, appearance_val={request.appearance[:50] if request.appearance else 'empty'}"
    )
    if request.appearance:
        from core.config import settings

        logger.info(
            f"Sprite settings: api_key={bool(settings.pixellab_api_key)}, bucket={settings.SPRITE_S3_BUCKET}, cdn={settings.SPRITE_CDN_URL}"
        )
        if settings.pixellab_api_key and settings.SPRITE_S3_BUCKET and settings.SPRITE_CDN_URL:
            import asyncio
            from core.database import get_session_factory

            _agent_id = agent.id  # capture before session closes

            async def _generate_sprite():
                logger.info(f"_generate_sprite started for agent {_agent_id}")
                try:
                    from core.services.pixellab_service import PixelLabService
                    from core.services.sprite_storage import download_walk_spritesheet, upload_sprite_to_s3

                    pxl = PixelLabService(api_key=settings.pixellab_api_key)
                    logger.info(f"Calling PixelLab create_character for {_agent_id}")
                    char_id = await pxl.create_character(
                        description=request.appearance,
                    )
                    logger.info(f"PixelLab returned char_id={char_id} for {_agent_id}")
                    # Store character ID
                    session_factory = get_session_factory()
                    async with session_factory() as session:
                        from sqlalchemy import update
                        from models.town import TownAgent as TA

                        await session.execute(
                            update(TA).where(TA.id == _agent_id).values(pixellab_character_id=char_id)
                        )
                        await session.commit()
                    # Queue animations
                    await pxl.generate_all_animations(char_id)
                    logger.info(f"PixelLab character {char_id} created for {agent.agent_name}")

                    # Poll for completion and download sprite
                    for _ in range(30):  # 30 x 10s = 5 minutes max
                        await asyncio.sleep(10)
                        png_bytes = await download_walk_spritesheet(settings.pixellab_api_key, char_id)
                        if png_bytes:
                            s3_key = await asyncio.to_thread(
                                upload_sprite_to_s3, png_bytes, str(_agent_id), settings.SPRITE_S3_BUCKET
                            )
                            cdn_url = f"{settings.SPRITE_CDN_URL}/{s3_key}"
                            async with session_factory() as session:
                                await session.execute(
                                    update(TA).where(TA.id == _agent_id).values(sprite_ready=True, sprite_url=cdn_url)
                                )
                                await session.commit()
                            logger.info(f"Sprite ready for agent {_agent_id}")
                            _notify_state_changed()
                            return
                    logger.warning(f"Sprite generation timed out for agent {_agent_id}")
                except Exception as e:
                    logger.exception(f"PixelLab sprite generation failed for {_agent_id}: {e}")

            task = asyncio.create_task(_generate_sprite())
            _background_sprite_tasks.add(task)
            task.add_done_callback(_background_sprite_tasks.discard)

    return {
        "agent_id": str(agent.id),
        "agent_name": agent.agent_name,
        "display_name": agent.display_name,
        "position": {"x": float(spawn["x"]), "y": float(spawn["y"])},
        "status": "generating_sprite",
        "ws_url": _TOWN_WS_URL,
        "api_url": _TOWN_API_URL,
        "message": f"Welcome to GooseTown, {agent.display_name}!",
    }


@router.get("/agent/status")
async def get_agent_status(
    agent_name: str = Query(...),
    token_info: tuple = Depends(get_town_token_user),
    db: AsyncSession = Depends(get_db),
):
    """Check agent sprite readiness. Polls PixelLab if sprite not yet downloaded."""
    from core.config import settings
    from sqlalchemy import select

    user_id, _ = token_info
    result = await db.execute(
        select(TownAgent).where(
            TownAgent.user_id == user_id,
            TownAgent.agent_name == agent_name,
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(404, "Agent not found")

    # Already done
    if agent.sprite_ready and agent.sprite_url:
        return {
            "agent_name": agent.agent_name,
            "sprite_ready": True,
            "sprite_url": agent.sprite_url,
        }

    # No PixelLab character queued
    if not agent.pixellab_character_id:
        return {
            "agent_name": agent.agent_name,
            "sprite_ready": False,
            "sprite_url": None,
        }

    # Check PixelLab and download/upload if ready
    if settings.pixellab_api_key and settings.SPRITE_S3_BUCKET:
        try:
            import asyncio
            from core.services.sprite_storage import download_walk_spritesheet, upload_sprite_to_s3

            png_bytes = await download_walk_spritesheet(
                settings.pixellab_api_key,
                agent.pixellab_character_id,
            )
            if png_bytes:
                s3_key = await asyncio.to_thread(
                    upload_sprite_to_s3, png_bytes, str(agent.id), settings.SPRITE_S3_BUCKET
                )
                cdn_url = f"{settings.SPRITE_CDN_URL}/{s3_key}"
                agent.sprite_ready = True
                agent.sprite_url = cdn_url
                await db.commit()
                return {
                    "agent_name": agent.agent_name,
                    "sprite_ready": True,
                    "sprite_url": cdn_url,
                }
        except Exception as e:
            logger.warning(f"Sprite status check failed: {e}")

    return {
        "agent_name": agent.agent_name,
        "sprite_ready": False,
        "sprite_url": None,
    }


# ===========================================================================
# Isol8-native endpoints (authenticated)
# ===========================================================================


@router.get("/apartment", response_model=ApartmentResponse)
async def get_apartment(
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the user's apartment view — their agents and recent activity."""
    from sqlalchemy import select
    from models.town import TownAgent, TownState

    result = await db.execute(
        select(TownAgent, TownState)
        .outerjoin(TownState, TownState.agent_id == TownAgent.id)
        .where(
            TownAgent.user_id == auth.user_id,
            TownAgent.is_active.is_(True),
        )
    )
    rows = result.all()

    agents = []
    for agent, state in rows:
        # Determine current spot from position
        current_spot = None
        if state and state.position_x is not None and state.position_y is not None:
            from core.apartment_constants import APARTMENT_SPOTS

            for spot_id, spot in APARTMENT_SPOTS.items():
                if abs(state.position_x - spot["x"]) < 0.5 and abs(state.position_y - spot["y"]) < 0.5:
                    current_spot = spot_id
                    break

        agents.append(
            ApartmentAgentState(
                agent_id=agent.id,
                agent_name=agent.agent_name,
                display_name=agent.display_name,
                character=agent.character,
                location_context=(state.location_context or "apartment") if state else "apartment",
                current_location=state.current_location if state else None,
                current_activity=state.current_activity if state else None,
                mood=state.mood if state else None,
                energy=state.energy if state and state.energy is not None else 100,
                status_message=state.status_message if state else None,
                position_x=state.position_x if state and state.position_x is not None else 0.0,
                position_y=state.position_y if state and state.position_y is not None else 0.0,
                speed=state.speed if state and state.speed is not None else 0.0,
                facing_x=state.facing_x if state and state.facing_x is not None else 0.0,
                facing_y=state.facing_y if state and state.facing_y is not None else 1.0,
                current_spot=current_spot,
                is_active=agent.is_active,
                sprite_url=agent.sprite_url if agent.sprite_ready else None,
            )
        )

    return ApartmentResponse(agents=agents, activity=[])


@router.post("/instance")
async def get_or_create_instance(
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get existing instance or create a new one. Returns town_token."""
    from core.town_token import sign_town_token

    service = TownService(db)
    instance = await service.get_active_instance(auth.user_id)

    if not instance:
        instance = await service.create_instance(auth.user_id)
        await db.commit()
    elif "." not in instance.town_token:
        # Re-sign legacy unsigned tokens
        instance.town_token = sign_town_token(auth.user_id, str(instance.id))
        await db.commit()

    agents = await service.get_instance_agents(instance.id)

    return {
        "town_token": instance.town_token,
        "apartment_unit": instance.apartment_unit,
        "agents": [
            {"agent_name": a.agent_name, "display_name": a.display_name, "sprite_url": a.sprite_url} for a in agents
        ],
    }


@router.get("/conversations", response_model=TownConversationsListResponse)
async def get_conversations(
    limit: int = 20,
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get recent public conversations."""
    service = TownService(db)
    convos = await service.get_recent_conversations(limit=limit)

    responses = []
    for c in convos:
        agent_a = await service.get_town_agent_by_id(c.participant_a_id)
        agent_b = await service.get_town_agent_by_id(c.participant_b_id)

        responses.append(
            TownConversationResponse(
                id=c.id,
                participant_a=agent_a.display_name if agent_a else "Unknown",
                participant_b=agent_b.display_name if agent_b else "Unknown",
                location=c.location,
                started_at=c.started_at,
                ended_at=c.ended_at,
                turn_count=c.turn_count,
                topic_summary=c.topic_summary,
                public_log=[ConversationTurn(speaker=t["speaker"], text=t["text"]) for t in (c.public_log or [])],
            )
        )

    return TownConversationsListResponse(conversations=responses)
