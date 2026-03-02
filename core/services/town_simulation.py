"""GooseTown simulation engine.

Runs as an asyncio background task inside FastAPI. Manages agent movement,
state transitions, and event dispatch to agent WebSocket connections.

The simulation is THIN -- it does NOT make decisions for agents. It only:
- Interpolates movement toward target_x/target_y
- Detects arrivals and pushes "arrived" events
- Detects nearby agents and pushes "nearby" events
- Handles transition states (going_home -> sleeping)
- Detects inactive agents and sends them home
- Broadcasts state to viewers
"""

import asyncio
import logging
import math
import random
from datetime import datetime, timezone, timedelta
from typing import Callable, Optional, Set, Tuple

from core.town_constants import (
    DEFAULT_CHARACTERS,
    SYSTEM_USER_ID,
    TOWN_LOCATIONS,
)

logger = logging.getLogger(__name__)

TICK_INTERVAL = 2.0  # seconds between simulation ticks
AGENT_SPEED = 0.6  # tiles per tick (~0.3 tiles/sec, natural walking pace)
ARRIVAL_THRESHOLD = 0.5  # tiles to consider "arrived"
DECISION_COOLDOWN = 10.0  # seconds idle before picking new destination
CONVERSATION_COOLDOWN = 120.0  # seconds between conversations
PROXIMITY_THRESHOLD = 3.0  # tiles to be "nearby"
INACTIVE_TIMEOUT = timedelta(minutes=5)  # send home after 5min without heartbeat


class TownSimulation:
    """Manages the GooseTown simulation loop."""

    def __init__(self, db_factory, notify_fn: Optional[Callable] = None):
        """Initialize with a database session factory.

        Args:
            db_factory: Callable that returns an async context manager for DB sessions
            notify_fn: Optional callback to push state to WebSocket viewers
        """
        self._db_factory = db_factory
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._notify_fn = notify_fn
        # Track which agent pairs were nearby last tick (frozenset of agent_name pairs)
        self._nearby_pairs: Set[frozenset] = set()
        # Lazy-initialized management API client for pushing events to agents
        self._mgmt_client = None
        self._mgmt_client_failed = False

    def _get_mgmt_client(self):
        """Lazily create ManagementApiClient. Returns None if unavailable."""
        if self._mgmt_client is not None:
            return self._mgmt_client
        if self._mgmt_client_failed:
            return None
        try:
            from core.services.management_api_client import ManagementApiClient

            self._mgmt_client = ManagementApiClient()
            return self._mgmt_client
        except Exception:
            logger.debug("ManagementApiClient not available (expected in local dev)")
            self._mgmt_client_failed = True
            return None

    def _get_ws_manager(self):
        """Get the TownAgentWsManager singleton."""
        from core.services.town_agent_ws import get_town_agent_ws_manager

        return get_town_agent_ws_manager()

    async def start(self):
        """Start the simulation background task."""
        if self._running:
            return
        self._running = True
        await self._seed_default_agents()
        self._task = asyncio.create_task(self._run_loop())
        logger.info("GooseTown simulation started")

    async def stop(self):
        """Stop the simulation."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("GooseTown simulation stopped")

    def set_notify_fn(self, fn: Callable):
        """Set the WebSocket push callback (called after state changes)."""
        self._notify_fn = fn

    async def _seed_default_agents(self):
        """Seed default agents into the DB if they don't already exist."""
        from core.services.town_service import TownService

        try:
            async with self._db_factory() as db:
                service = TownService(db)
                for agent in DEFAULT_CHARACTERS:
                    await service.seed_agent(
                        user_id=SYSTEM_USER_ID,
                        agent_name=agent["agent_name"],
                        display_name=agent["name"],
                        personality_summary=agent["identity"][:200],
                        position_x=agent["spawn"]["x"],
                        position_y=agent["spawn"]["y"],
                        home_location=agent["home"],
                    )
                await db.commit()
            logger.info(f"Seeded {len(DEFAULT_CHARACTERS)} default agents")
        except Exception as e:
            logger.error(f"Failed to seed default agents: {e}", exc_info=True)

    async def _run_loop(self):
        """Main simulation tick loop."""
        while self._running:
            try:
                await self._tick()
            except Exception as e:
                logger.error(f"GooseTown tick error: {e}", exc_info=True)

            await asyncio.sleep(TICK_INTERVAL)

    async def _tick(self):
        """Execute one simulation tick.

        Steps:
        1. Move agents toward target_x/target_y
        2. Detect arrivals -> push "arrived" event
        3. Handle going_home -> sleeping transition
        4. Detect inactive agents -> send home
        5. Auto-assign destinations for system agents
        6. Detect proximity changes -> push "nearby" events
        7. Broadcast state to viewers
        """
        from core.services.town_service import TownService

        async with self._db_factory() as db:
            service = TownService(db)
            states = await service.get_town_state()

            if not states:
                return

            now = datetime.now(timezone.utc)
            ws_manager = self._get_ws_manager()

            # Collect events to push after DB updates
            events_to_push: list[tuple[str, dict]] = []  # (agent_name, payload)

            for agent_state in states:
                agent_id = agent_state["agent_id"]
                agent_name = agent_state["agent_name"]
                location_state = agent_state["location_state"] or "active"
                user_id = agent_state["user_id"]

                # Skip sleeping agents entirely
                if location_state == "sleeping":
                    continue

                # Skip agents in a conversation (don't move them)
                if agent_state["current_conversation_id"] is not None:
                    continue

                # --- Movement toward target_x/target_y ---
                tx = agent_state["target_x"]
                ty = agent_state["target_y"]

                if tx is not None and ty is not None:
                    new_x, new_y, arrived = self._move_toward(
                        agent_state["position_x"],
                        agent_state["position_y"],
                        tx,
                        ty,
                        AGENT_SPEED,
                    )

                    # Compute facing direction from movement delta
                    dx = new_x - agent_state["position_x"]
                    dy = new_y - agent_state["position_y"]
                    move_dist = math.sqrt(dx * dx + dy * dy)

                    update = {
                        "position_x": new_x,
                        "position_y": new_y,
                        "speed": AGENT_SPEED,
                    }

                    if move_dist > 0.001:
                        update["facing_x"] = dx / move_dist
                        update["facing_y"] = dy / move_dist

                    if arrived:
                        update["target_x"] = None
                        update["target_y"] = None
                        update["speed"] = 0.0
                        update["current_activity"] = "idle"

                        # Set current_location from target_location if provided
                        if agent_state["target_location"]:
                            update["current_location"] = agent_state["target_location"]
                            update["target_location"] = None

                        # Handle going_home -> sleeping transition
                        if location_state == "going_home":
                            update["location_state"] = "sleeping"
                            logger.debug("Agent %s arrived home, now sleeping", agent_name)
                        else:
                            # Push "arrived" event to connected agent
                            events_to_push.append(
                                (
                                    agent_name,
                                    {
                                        "type": "town_event",
                                        "event": "arrived",
                                        "location": update.get(
                                            "current_location",
                                            agent_state["current_location"],
                                        ),
                                        "position": {"x": new_x, "y": new_y},
                                    },
                                )
                            )

                    await service.update_agent_state(agent_id, **update)

                # --- No target: auto-assign for system agents only ---
                elif (
                    user_id == SYSTEM_USER_ID
                    and agent_state["current_activity"] == "idle"
                    and location_state == "active"
                ):
                    last_decision = agent_state.get("last_decision_at")
                    if not last_decision or (now - last_decision).total_seconds() > DECISION_COOLDOWN:
                        target_loc = self._pick_random_location(exclude=agent_state["current_location"])
                        target_coords = TOWN_LOCATIONS.get(target_loc)
                        if target_coords:
                            await service.update_agent_state(
                                agent_id,
                                target_x=target_coords["x"],
                                target_y=target_coords["y"],
                                target_location=target_loc,
                                current_activity="walking",
                                speed=AGENT_SPEED,
                                last_decision_at=now,
                            )

                # --- Inactive detection: send home if no heartbeat for 5min ---
                if (
                    location_state == "active"
                    and user_id != SYSTEM_USER_ID
                    and not ws_manager.is_agent_connected(agent_name)
                ):
                    heartbeat = agent_state["last_heartbeat_at"]
                    if heartbeat is None or (now - heartbeat) > INACTIVE_TIMEOUT:
                        home_loc = agent_state["home_location"] or "apartment"
                        home_coords = TOWN_LOCATIONS.get(home_loc, TOWN_LOCATIONS.get("apartment"))
                        if home_coords:
                            await service.update_agent_state(
                                agent_id,
                                location_state="going_home",
                                target_x=home_coords["x"],
                                target_y=home_coords["y"],
                                target_location=home_loc,
                                current_activity="walking",
                                speed=AGENT_SPEED,
                            )
                            logger.info(
                                "Agent %s inactive for >5min, sending home",
                                agent_name,
                            )

            # --- Proximity detection ---
            current_nearby = set()
            active_states = [
                s
                for s in states
                if (s["location_state"] or "active") != "sleeping" and s["current_conversation_id"] is None
            ]

            for i, a in enumerate(active_states):
                for b in active_states[i + 1 :]:
                    dist = self._calculate_distance(
                        a["position_x"],
                        a["position_y"],
                        b["position_x"],
                        b["position_y"],
                    )
                    if dist <= PROXIMITY_THRESHOLD:
                        pair = frozenset((a["agent_name"], b["agent_name"]))
                        current_nearby.add(pair)

                        # Only push event for NEW proximity (not already nearby last tick)
                        if pair not in self._nearby_pairs:
                            # Push to agent a if connected
                            events_to_push.append(
                                (
                                    a["agent_name"],
                                    {
                                        "type": "town_event",
                                        "event": "nearby",
                                        "nearby_agent": b["agent_name"],
                                        "nearby_display_name": b["display_name"],
                                        "distance": round(dist, 2),
                                    },
                                )
                            )
                            # Push to agent b if connected
                            events_to_push.append(
                                (
                                    b["agent_name"],
                                    {
                                        "type": "town_event",
                                        "event": "nearby",
                                        "nearby_agent": a["agent_name"],
                                        "nearby_display_name": a["display_name"],
                                        "distance": round(dist, 2),
                                    },
                                )
                            )

            self._nearby_pairs = current_nearby

            await db.commit()

        # --- Push events to connected agents ---
        self._push_agent_events(ws_manager, events_to_push)

        # Push updated state to WebSocket viewers
        if self._notify_fn:
            try:
                self._notify_fn()
            except Exception as e:
                logger.debug(f"WS notify failed: {e}")

    def _push_agent_events(
        self,
        ws_manager,
        events: list[tuple[str, dict]],
    ):
        """Push events to connected agents via Management API.

        Best-effort: logs errors but never crashes the tick.
        """
        if not events:
            return

        mgmt = self._get_mgmt_client()
        if mgmt is None:
            return

        for agent_name, payload in events:
            connection_id = ws_manager.get_agent_connection_id(agent_name)
            if connection_id is None:
                continue
            try:
                mgmt.send_message(connection_id, payload)
            except Exception as e:
                logger.debug("Failed to push event to agent %s: %s", agent_name, e)

    def _pick_random_location(self, exclude: Optional[str] = None) -> str:
        """Pick a random town location, excluding current."""
        choices = [loc for loc in TOWN_LOCATIONS if loc != exclude]
        return random.choice(choices)

    @staticmethod
    def _calculate_distance(x1: float, y1: float, x2: float, y2: float) -> float:
        """Euclidean distance between two points."""
        return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)

    @staticmethod
    def _move_toward(
        current_x: float,
        current_y: float,
        target_x: float,
        target_y: float,
        speed: float,
    ) -> Tuple[float, float, bool]:
        """Move toward target at given speed. Returns (new_x, new_y, arrived)."""
        dx = target_x - current_x
        dy = target_y - current_y
        dist = math.sqrt(dx * dx + dy * dy)

        if dist <= speed:
            return target_x, target_y, True

        ratio = speed / dist
        return current_x + dx * ratio, current_y + dy * ratio, False

    @staticmethod
    def _conversation_probability(affinity: int) -> float:
        """Calculate conversation probability based on relationship affinity.

        Strangers (0): 15%
        Acquaintances (25): ~30%
        Friends (50): ~45%
        Close friends (75): ~60%
        Best friends (100): ~70%
        """
        base = 0.15
        bonus = (affinity / 100.0) * 0.55
        return min(0.70, base + bonus)
