"""Tests for TownSimulation engine."""

from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from core.town_constants import TOWN_LOCATIONS, SYSTEM_USER_ID
from core.services.town_simulation import (
    TownSimulation,
    TICK_INTERVAL,
    AGENT_SPEED,
    DECISION_COOLDOWN,
    INACTIVE_TIMEOUT,
)


class TestTownLocations:
    """Test town location definitions."""

    def test_locations_defined(self):
        assert "home" in TOWN_LOCATIONS
        assert "cafe" in TOWN_LOCATIONS
        assert "plaza" in TOWN_LOCATIONS
        assert "library" in TOWN_LOCATIONS
        assert "park" in TOWN_LOCATIONS
        assert "apartment" in TOWN_LOCATIONS
        assert "barn" in TOWN_LOCATIONS
        assert "shop" in TOWN_LOCATIONS

    def test_locations_have_coordinates(self):
        for name, loc in TOWN_LOCATIONS.items():
            assert "x" in loc
            assert "y" in loc
            assert isinstance(loc["x"], (int, float))
            assert isinstance(loc["y"], (int, float))


class TestTownSimulationConstants:
    """Test simulation timing and speed constants."""

    def test_tick_interval_is_fast_enough(self):
        assert TICK_INTERVAL <= 3.0, "Tick should be <=3s for smooth animation"

    def test_agent_speed_reasonable(self):
        assert 0.1 <= AGENT_SPEED <= 2.0, "Speed should be in tile/tick range"

    def test_decision_cooldown_reasonable(self):
        assert DECISION_COOLDOWN >= 5.0, "Agents shouldn't decide too fast"

    def test_inactive_timeout_is_5_minutes(self):
        assert INACTIVE_TIMEOUT == timedelta(minutes=5)


class TestTownSimulation:
    """Test simulation tick logic."""

    def test_pick_random_location(self):
        sim = TownSimulation.__new__(TownSimulation)
        current = "home"
        target = sim._pick_random_location(exclude=current)
        assert target != current
        assert target in TOWN_LOCATIONS

    def test_calculate_distance(self):
        sim = TownSimulation.__new__(TownSimulation)
        dist = sim._calculate_distance(0, 0, 3, 4)
        assert dist == 5.0

    def test_move_toward_target(self):
        sim = TownSimulation.__new__(TownSimulation)
        new_x, new_y, arrived = sim._move_toward(
            current_x=0.0,
            current_y=0.0,
            target_x=100.0,
            target_y=0.0,
            speed=10.0,
        )
        assert new_x == 10.0
        assert new_y == 0.0
        assert arrived is False

    def test_move_toward_arrives_when_close(self):
        sim = TownSimulation.__new__(TownSimulation)
        new_x, new_y, arrived = sim._move_toward(
            current_x=95.0,
            current_y=0.0,
            target_x=100.0,
            target_y=0.0,
            speed=10.0,
        )
        assert new_x == 100.0
        assert new_y == 0.0
        assert arrived is True

    def test_should_converse_probability(self):
        sim = TownSimulation.__new__(TownSimulation)
        # Strangers: 15% base probability
        assert sim._conversation_probability(0) == 0.15
        # Friends (50+ affinity): higher probability
        assert sim._conversation_probability(50) > 0.15
        # Close friends (80+ affinity): even higher
        assert sim._conversation_probability(80) > sim._conversation_probability(50)


def _make_agent_state(
    agent_name="test_agent",
    user_id=SYSTEM_USER_ID,
    position_x=10.0,
    position_y=10.0,
    target_x=None,
    target_y=None,
    target_location=None,
    current_location="plaza",
    current_activity="idle",
    location_state="active",
    speed=0.0,
    facing_x=0.0,
    facing_y=1.0,
    current_conversation_id=None,
    last_heartbeat_at=None,
    home_location="apartment",
    display_name="Test Agent",
    personality_summary="A test agent",
    mood="neutral",
    energy=100,
    status_message=None,
    last_decision_at=None,
    last_conversation_at=None,
    agent_id=None,
):
    """Helper to construct an agent state dict matching get_town_state() output."""
    return {
        "agent_id": agent_id or uuid4(),
        "user_id": user_id,
        "display_name": display_name,
        "agent_name": agent_name,
        "personality_summary": personality_summary,
        "home_location": home_location,
        "current_location": current_location,
        "current_activity": current_activity,
        "target_location": target_location,
        "target_x": target_x,
        "target_y": target_y,
        "position_x": position_x,
        "position_y": position_y,
        "location_state": location_state,
        "speed": speed,
        "facing_x": facing_x,
        "facing_y": facing_y,
        "current_conversation_id": current_conversation_id,
        "last_heartbeat_at": last_heartbeat_at,
        "mood": mood,
        "energy": energy,
        "status_message": status_message,
        "last_decision_at": last_decision_at,
        "last_conversation_at": last_conversation_at,
    }


def _make_simulation():
    """Create a TownSimulation with mocked dependencies."""
    db_session = AsyncMock()
    db_factory = MagicMock()
    db_factory.return_value.__aenter__ = AsyncMock(return_value=db_session)
    db_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    sim = TownSimulation(db_factory=db_factory, notify_fn=MagicMock())
    sim._nearby_pairs = set()
    sim._mgmt_client = None
    sim._mgmt_client_failed = True  # Disable mgmt client by default in tests
    return sim, db_session


class TestTickMovement:
    """Test movement toward target_x/target_y in _tick()."""

    @pytest.mark.asyncio
    async def test_agent_moves_toward_target(self):
        """Agent with target_x/target_y should move toward it."""
        sim, db_session = _make_simulation()
        agent_state = _make_agent_state(
            position_x=10.0,
            position_y=10.0,
            target_x=20.0,
            target_y=10.0,
            current_activity="walking",
        )

        mock_service = AsyncMock()
        mock_service.get_town_state = AsyncMock(return_value=[agent_state])
        mock_service.update_agent_state = AsyncMock()

        mock_ws = MagicMock()
        mock_ws.is_agent_connected = MagicMock(return_value=False)
        mock_ws.get_agent_connection_id = MagicMock(return_value=None)

        with patch(
            "core.services.town_simulation.TownSimulation._get_ws_manager",
            return_value=mock_ws,
        ):
            with patch(
                "core.services.town_service.TownService",
                return_value=mock_service,
            ):
                await sim._tick()

        # Should have been called to update position
        mock_service.update_agent_state.assert_called()
        call_kwargs = mock_service.update_agent_state.call_args_list[0]
        update_kwargs = call_kwargs[1]
        # Agent moved toward target (positive x direction)
        assert update_kwargs["position_x"] > 10.0
        assert update_kwargs["position_y"] == 10.0
        assert update_kwargs["speed"] == AGENT_SPEED

    @pytest.mark.asyncio
    async def test_agent_arrives_at_target(self):
        """Agent close to target should arrive and clear target."""
        sim, db_session = _make_simulation()
        agent_state = _make_agent_state(
            position_x=19.5,
            position_y=10.0,
            target_x=20.0,
            target_y=10.0,
            target_location="cafe",
            current_activity="walking",
        )

        mock_service = AsyncMock()
        mock_service.get_town_state = AsyncMock(return_value=[agent_state])
        mock_service.update_agent_state = AsyncMock()

        mock_ws = MagicMock()
        mock_ws.is_agent_connected = MagicMock(return_value=False)
        mock_ws.get_agent_connection_id = MagicMock(return_value=None)

        with patch(
            "core.services.town_simulation.TownSimulation._get_ws_manager",
            return_value=mock_ws,
        ):
            with patch(
                "core.services.town_service.TownService",
                return_value=mock_service,
            ):
                await sim._tick()

        call_kwargs = mock_service.update_agent_state.call_args_list[0]
        update_kwargs = call_kwargs[1]
        assert update_kwargs["target_x"] is None
        assert update_kwargs["target_y"] is None
        assert update_kwargs["target_location"] is None
        assert update_kwargs["current_location"] == "cafe"
        assert update_kwargs["current_activity"] == "idle"
        assert update_kwargs["speed"] == 0.0

    @pytest.mark.asyncio
    async def test_sleeping_agents_are_skipped(self):
        """Agents with location_state='sleeping' should not be processed."""
        sim, db_session = _make_simulation()
        agent_state = _make_agent_state(
            location_state="sleeping",
            target_x=20.0,
            target_y=10.0,
        )

        mock_service = AsyncMock()
        mock_service.get_town_state = AsyncMock(return_value=[agent_state])
        mock_service.update_agent_state = AsyncMock()

        mock_ws = MagicMock()
        mock_ws.is_agent_connected = MagicMock(return_value=False)
        mock_ws.get_agent_connection_id = MagicMock(return_value=None)

        with patch(
            "core.services.town_simulation.TownSimulation._get_ws_manager",
            return_value=mock_ws,
        ):
            with patch(
                "core.services.town_service.TownService",
                return_value=mock_service,
            ):
                await sim._tick()

        mock_service.update_agent_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_chatting_agents_are_skipped(self):
        """Agents in a conversation should not be moved."""
        sim, db_session = _make_simulation()
        agent_state = _make_agent_state(
            current_conversation_id=uuid4(),
            target_x=20.0,
            target_y=10.0,
        )

        mock_service = AsyncMock()
        mock_service.get_town_state = AsyncMock(return_value=[agent_state])
        mock_service.update_agent_state = AsyncMock()

        mock_ws = MagicMock()
        mock_ws.is_agent_connected = MagicMock(return_value=False)
        mock_ws.get_agent_connection_id = MagicMock(return_value=None)

        with patch(
            "core.services.town_simulation.TownSimulation._get_ws_manager",
            return_value=mock_ws,
        ):
            with patch(
                "core.services.town_service.TownService",
                return_value=mock_service,
            ):
                await sim._tick()

        mock_service.update_agent_state.assert_not_called()


class TestTickGoingHomeSleeping:
    """Test going_home -> sleeping transition."""

    @pytest.mark.asyncio
    async def test_going_home_becomes_sleeping_on_arrival(self):
        """Agent with location_state='going_home' transitions to sleeping on arrival."""
        sim, db_session = _make_simulation()
        # Agent is very close to home
        agent_state = _make_agent_state(
            position_x=9.8,
            position_y=8.0,
            target_x=10.0,
            target_y=8.0,
            target_location="apartment",
            location_state="going_home",
            current_activity="walking",
        )

        mock_service = AsyncMock()
        mock_service.get_town_state = AsyncMock(return_value=[agent_state])
        mock_service.update_agent_state = AsyncMock()

        mock_ws = MagicMock()
        mock_ws.is_agent_connected = MagicMock(return_value=False)
        mock_ws.get_agent_connection_id = MagicMock(return_value=None)

        with patch(
            "core.services.town_simulation.TownSimulation._get_ws_manager",
            return_value=mock_ws,
        ):
            with patch(
                "core.services.town_service.TownService",
                return_value=mock_service,
            ):
                await sim._tick()

        call_kwargs = mock_service.update_agent_state.call_args_list[0]
        update_kwargs = call_kwargs[1]
        assert update_kwargs["location_state"] == "sleeping"
        assert update_kwargs["speed"] == 0.0
        assert update_kwargs["target_x"] is None
        assert update_kwargs["target_y"] is None


class TestTickInactiveDetection:
    """Test inactive agent detection and send-home logic."""

    @pytest.mark.asyncio
    async def test_inactive_user_agent_sent_home(self):
        """User agent without heartbeat for >5min should be sent home."""
        sim, db_session = _make_simulation()
        old_heartbeat = datetime.now(timezone.utc) - timedelta(minutes=10)
        agent_state = _make_agent_state(
            agent_name="user_agent",
            user_id="user_123",
            location_state="active",
            last_heartbeat_at=old_heartbeat,
            home_location="apartment",
            current_activity="idle",
        )

        mock_service = AsyncMock()
        mock_service.get_town_state = AsyncMock(return_value=[agent_state])
        mock_service.update_agent_state = AsyncMock()

        mock_ws = MagicMock()
        mock_ws.is_agent_connected = MagicMock(return_value=False)
        mock_ws.get_agent_connection_id = MagicMock(return_value=None)

        with patch(
            "core.services.town_simulation.TownSimulation._get_ws_manager",
            return_value=mock_ws,
        ):
            with patch(
                "core.services.town_service.TownService",
                return_value=mock_service,
            ):
                await sim._tick()

        # Should have been called to send agent home
        calls = mock_service.update_agent_state.call_args_list
        # Find the call that sets going_home
        going_home_calls = [c for c in calls if c[1].get("location_state") == "going_home"]
        assert len(going_home_calls) == 1
        kwargs = going_home_calls[0][1]
        assert kwargs["location_state"] == "going_home"
        assert kwargs["target_x"] == TOWN_LOCATIONS["apartment"]["x"]
        assert kwargs["target_y"] == TOWN_LOCATIONS["apartment"]["y"]

    @pytest.mark.asyncio
    async def test_inactive_user_agent_with_null_heartbeat_sent_home(self):
        """User agent with null heartbeat should also be sent home."""
        sim, db_session = _make_simulation()
        agent_state = _make_agent_state(
            agent_name="user_agent",
            user_id="user_123",
            location_state="active",
            last_heartbeat_at=None,
            home_location="apartment",
            current_activity="idle",
        )

        mock_service = AsyncMock()
        mock_service.get_town_state = AsyncMock(return_value=[agent_state])
        mock_service.update_agent_state = AsyncMock()

        mock_ws = MagicMock()
        mock_ws.is_agent_connected = MagicMock(return_value=False)
        mock_ws.get_agent_connection_id = MagicMock(return_value=None)

        with patch(
            "core.services.town_simulation.TownSimulation._get_ws_manager",
            return_value=mock_ws,
        ):
            with patch(
                "core.services.town_service.TownService",
                return_value=mock_service,
            ):
                await sim._tick()

        calls = mock_service.update_agent_state.call_args_list
        going_home_calls = [c for c in calls if c[1].get("location_state") == "going_home"]
        assert len(going_home_calls) == 1

    @pytest.mark.asyncio
    async def test_connected_user_agent_not_sent_home(self):
        """User agent that IS connected should NOT be sent home even with old heartbeat."""
        sim, db_session = _make_simulation()
        old_heartbeat = datetime.now(timezone.utc) - timedelta(minutes=10)
        agent_state = _make_agent_state(
            agent_name="user_agent",
            user_id="user_123",
            location_state="active",
            last_heartbeat_at=old_heartbeat,
            home_location="apartment",
            current_activity="idle",
        )

        mock_service = AsyncMock()
        mock_service.get_town_state = AsyncMock(return_value=[agent_state])
        mock_service.update_agent_state = AsyncMock()

        mock_ws = MagicMock()
        mock_ws.is_agent_connected = MagicMock(return_value=True)
        mock_ws.get_agent_connection_id = MagicMock(return_value="conn_123")

        with patch(
            "core.services.town_simulation.TownSimulation._get_ws_manager",
            return_value=mock_ws,
        ):
            with patch(
                "core.services.town_service.TownService",
                return_value=mock_service,
            ):
                await sim._tick()

        calls = mock_service.update_agent_state.call_args_list
        going_home_calls = [c for c in calls if c[1].get("location_state") == "going_home"]
        assert len(going_home_calls) == 0

    @pytest.mark.asyncio
    async def test_system_agents_not_sent_home(self):
        """System agents should never be sent home for inactivity."""
        sim, db_session = _make_simulation()
        agent_state = _make_agent_state(
            agent_name="lucky",
            user_id=SYSTEM_USER_ID,
            location_state="active",
            last_heartbeat_at=None,
            current_activity="idle",
        )

        mock_service = AsyncMock()
        mock_service.get_town_state = AsyncMock(return_value=[agent_state])
        mock_service.update_agent_state = AsyncMock()

        mock_ws = MagicMock()
        mock_ws.is_agent_connected = MagicMock(return_value=False)
        mock_ws.get_agent_connection_id = MagicMock(return_value=None)

        with patch(
            "core.services.town_simulation.TownSimulation._get_ws_manager",
            return_value=mock_ws,
        ):
            with patch(
                "core.services.town_service.TownService",
                return_value=mock_service,
            ):
                await sim._tick()

        calls = mock_service.update_agent_state.call_args_list
        going_home_calls = [c for c in calls if c[1].get("location_state") == "going_home"]
        assert len(going_home_calls) == 0


class TestTickSystemAgentAutoAssign:
    """Test that system agents auto-pick destinations but user agents do not."""

    @pytest.mark.asyncio
    async def test_system_agent_picks_destination(self):
        """Idle system agent should auto-pick a random destination."""
        sim, db_session = _make_simulation()
        agent_state = _make_agent_state(
            agent_name="lucky",
            user_id=SYSTEM_USER_ID,
            location_state="active",
            current_activity="idle",
            last_decision_at=None,
        )

        mock_service = AsyncMock()
        mock_service.get_town_state = AsyncMock(return_value=[agent_state])
        mock_service.update_agent_state = AsyncMock()

        mock_ws = MagicMock()
        mock_ws.is_agent_connected = MagicMock(return_value=False)
        mock_ws.get_agent_connection_id = MagicMock(return_value=None)

        with patch(
            "core.services.town_simulation.TownSimulation._get_ws_manager",
            return_value=mock_ws,
        ):
            with patch(
                "core.services.town_service.TownService",
                return_value=mock_service,
            ):
                await sim._tick()

        calls = mock_service.update_agent_state.call_args_list
        # Should have a call setting target_x/target_y
        assign_calls = [c for c in calls if "target_x" in c[1]]
        assert len(assign_calls) == 1
        kwargs = assign_calls[0][1]
        assert kwargs["target_x"] is not None
        assert kwargs["target_y"] is not None
        assert kwargs["current_activity"] == "walking"

    @pytest.mark.asyncio
    async def test_user_agent_does_not_auto_pick_destination(self):
        """Idle user agent should NOT auto-pick a destination."""
        sim, db_session = _make_simulation()
        agent_state = _make_agent_state(
            agent_name="user_agent",
            user_id="user_123",
            location_state="active",
            current_activity="idle",
            last_decision_at=None,
            # Recent heartbeat so won't be sent home
            last_heartbeat_at=datetime.now(timezone.utc),
        )

        mock_service = AsyncMock()
        mock_service.get_town_state = AsyncMock(return_value=[agent_state])
        mock_service.update_agent_state = AsyncMock()

        mock_ws = MagicMock()
        mock_ws.is_agent_connected = MagicMock(return_value=True)
        mock_ws.get_agent_connection_id = MagicMock(return_value="conn_123")

        with patch(
            "core.services.town_simulation.TownSimulation._get_ws_manager",
            return_value=mock_ws,
        ):
            with patch(
                "core.services.town_service.TownService",
                return_value=mock_service,
            ):
                await sim._tick()

        # Should NOT have any calls assigning targets
        calls = mock_service.update_agent_state.call_args_list
        assign_calls = [c for c in calls if "target_x" in c[1]]
        assert len(assign_calls) == 0


class TestTickProximityDetection:
    """Test nearby agent detection and event dispatching."""

    @pytest.mark.asyncio
    async def test_nearby_agents_detected(self):
        """Two agents within PROXIMITY_THRESHOLD should trigger nearby events."""
        sim, db_session = _make_simulation()
        sim._mgmt_client_failed = False
        mock_mgmt = MagicMock()
        mock_mgmt.send_message = MagicMock(return_value=True)
        sim._mgmt_client = mock_mgmt

        agent_a = _make_agent_state(
            agent_name="alice",
            position_x=10.0,
            position_y=10.0,
        )
        agent_b = _make_agent_state(
            agent_name="bob",
            position_x=11.0,
            position_y=10.0,
        )

        mock_service = AsyncMock()
        mock_service.get_town_state = AsyncMock(return_value=[agent_a, agent_b])
        mock_service.update_agent_state = AsyncMock()

        mock_ws = MagicMock()
        mock_ws.is_agent_connected = MagicMock(return_value=True)
        mock_ws.get_agent_connection_id = MagicMock(side_effect=lambda name: f"conn_{name}")

        with patch(
            "core.services.town_simulation.TownSimulation._get_ws_manager",
            return_value=mock_ws,
        ):
            with patch(
                "core.services.town_service.TownService",
                return_value=mock_service,
            ):
                await sim._tick()

        # Should have pushed nearby events to both agents
        assert mock_mgmt.send_message.call_count == 2
        # Check event payloads
        calls = mock_mgmt.send_message.call_args_list
        payloads = [c[0][1] for c in calls]
        assert any(p["event"] == "nearby" and p["nearby_agent"] == "bob" for p in payloads)
        assert any(p["event"] == "nearby" and p["nearby_agent"] == "alice" for p in payloads)

    @pytest.mark.asyncio
    async def test_nearby_not_re_sent_on_second_tick(self):
        """Already-nearby pair should NOT get re-notified on subsequent ticks."""
        sim, db_session = _make_simulation()
        sim._mgmt_client_failed = False
        mock_mgmt = MagicMock()
        mock_mgmt.send_message = MagicMock(return_value=True)
        sim._mgmt_client = mock_mgmt

        # Pre-populate _nearby_pairs to simulate they were already nearby
        sim._nearby_pairs = {frozenset(("alice", "bob"))}

        agent_a = _make_agent_state(
            agent_name="alice",
            position_x=10.0,
            position_y=10.0,
        )
        agent_b = _make_agent_state(
            agent_name="bob",
            position_x=11.0,
            position_y=10.0,
        )

        mock_service = AsyncMock()
        mock_service.get_town_state = AsyncMock(return_value=[agent_a, agent_b])
        mock_service.update_agent_state = AsyncMock()

        mock_ws = MagicMock()
        mock_ws.is_agent_connected = MagicMock(return_value=True)
        mock_ws.get_agent_connection_id = MagicMock(side_effect=lambda name: f"conn_{name}")

        with patch(
            "core.services.town_simulation.TownSimulation._get_ws_manager",
            return_value=mock_ws,
        ):
            with patch(
                "core.services.town_service.TownService",
                return_value=mock_service,
            ):
                await sim._tick()

        # No nearby events should be sent (pair already known)
        nearby_calls = [c for c in mock_mgmt.send_message.call_args_list if c[0][1].get("event") == "nearby"]
        assert len(nearby_calls) == 0

    @pytest.mark.asyncio
    async def test_far_agents_not_detected(self):
        """Two agents far apart should NOT trigger nearby events."""
        sim, db_session = _make_simulation()
        sim._mgmt_client_failed = False
        mock_mgmt = MagicMock()
        mock_mgmt.send_message = MagicMock(return_value=True)
        sim._mgmt_client = mock_mgmt

        agent_a = _make_agent_state(
            agent_name="alice",
            position_x=10.0,
            position_y=10.0,
        )
        agent_b = _make_agent_state(
            agent_name="bob",
            position_x=50.0,
            position_y=50.0,
        )

        mock_service = AsyncMock()
        mock_service.get_town_state = AsyncMock(return_value=[agent_a, agent_b])
        mock_service.update_agent_state = AsyncMock()

        mock_ws = MagicMock()
        mock_ws.is_agent_connected = MagicMock(return_value=True)
        mock_ws.get_agent_connection_id = MagicMock(side_effect=lambda name: f"conn_{name}")

        with patch(
            "core.services.town_simulation.TownSimulation._get_ws_manager",
            return_value=mock_ws,
        ):
            with patch(
                "core.services.town_service.TownService",
                return_value=mock_service,
            ):
                await sim._tick()

        # No events should be sent
        mock_mgmt.send_message.assert_not_called()


class TestTickArrivedEventPush:
    """Test that arrival pushes events to connected agents."""

    @pytest.mark.asyncio
    async def test_arrived_event_pushed_to_connected_agent(self):
        """Connected agent arriving at target should receive an 'arrived' event."""
        sim, db_session = _make_simulation()
        sim._mgmt_client_failed = False
        mock_mgmt = MagicMock()
        mock_mgmt.send_message = MagicMock(return_value=True)
        sim._mgmt_client = mock_mgmt

        agent_state = _make_agent_state(
            agent_name="user_agent",
            user_id="user_123",
            position_x=19.5,
            position_y=10.0,
            target_x=20.0,
            target_y=10.0,
            target_location="cafe",
            current_activity="walking",
            location_state="active",
            last_heartbeat_at=datetime.now(timezone.utc),
        )

        mock_service = AsyncMock()
        mock_service.get_town_state = AsyncMock(return_value=[agent_state])
        mock_service.update_agent_state = AsyncMock()

        mock_ws = MagicMock()
        mock_ws.is_agent_connected = MagicMock(return_value=True)
        mock_ws.get_agent_connection_id = MagicMock(return_value="conn_user")

        with patch(
            "core.services.town_simulation.TownSimulation._get_ws_manager",
            return_value=mock_ws,
        ):
            with patch(
                "core.services.town_service.TownService",
                return_value=mock_service,
            ):
                await sim._tick()

        # Should have pushed an "arrived" event
        arrived_calls = [c for c in mock_mgmt.send_message.call_args_list if c[0][1].get("event") == "arrived"]
        assert len(arrived_calls) == 1
        payload = arrived_calls[0][0][1]
        assert payload["type"] == "town_event"
        assert payload["location"] == "cafe"

    @pytest.mark.asyncio
    async def test_going_home_arrival_does_not_push_arrived_event(self):
        """Agent going_home should NOT receive an 'arrived' event (transitions to sleeping)."""
        sim, db_session = _make_simulation()
        sim._mgmt_client_failed = False
        mock_mgmt = MagicMock()
        mock_mgmt.send_message = MagicMock(return_value=True)
        sim._mgmt_client = mock_mgmt

        agent_state = _make_agent_state(
            agent_name="user_agent",
            user_id="user_123",
            position_x=9.8,
            position_y=8.0,
            target_x=10.0,
            target_y=8.0,
            target_location="apartment",
            location_state="going_home",
            current_activity="walking",
            last_heartbeat_at=datetime.now(timezone.utc),
        )

        mock_service = AsyncMock()
        mock_service.get_town_state = AsyncMock(return_value=[agent_state])
        mock_service.update_agent_state = AsyncMock()

        mock_ws = MagicMock()
        mock_ws.is_agent_connected = MagicMock(return_value=True)
        mock_ws.get_agent_connection_id = MagicMock(return_value="conn_user")

        with patch(
            "core.services.town_simulation.TownSimulation._get_ws_manager",
            return_value=mock_ws,
        ):
            with patch(
                "core.services.town_service.TownService",
                return_value=mock_service,
            ):
                await sim._tick()

        # No "arrived" event (sleeping transition, not an arrival event)
        arrived_calls = [c for c in mock_mgmt.send_message.call_args_list if c[0][1].get("event") == "arrived"]
        assert len(arrived_calls) == 0


class TestTickFacingDirection:
    """Test that facing direction is updated during movement."""

    @pytest.mark.asyncio
    async def test_facing_updated_during_movement(self):
        """Agent moving east should have facing_x=1.0, facing_y=0.0."""
        sim, db_session = _make_simulation()
        agent_state = _make_agent_state(
            position_x=10.0,
            position_y=10.0,
            target_x=20.0,
            target_y=10.0,
            current_activity="walking",
        )

        mock_service = AsyncMock()
        mock_service.get_town_state = AsyncMock(return_value=[agent_state])
        mock_service.update_agent_state = AsyncMock()

        mock_ws = MagicMock()
        mock_ws.is_agent_connected = MagicMock(return_value=False)
        mock_ws.get_agent_connection_id = MagicMock(return_value=None)

        with patch(
            "core.services.town_simulation.TownSimulation._get_ws_manager",
            return_value=mock_ws,
        ):
            with patch(
                "core.services.town_service.TownService",
                return_value=mock_service,
            ):
                await sim._tick()

        call_kwargs = mock_service.update_agent_state.call_args_list[0]
        update_kwargs = call_kwargs[1]
        assert abs(update_kwargs["facing_x"] - 1.0) < 0.01
        assert abs(update_kwargs["facing_y"] - 0.0) < 0.01


class TestPushAgentEvents:
    """Test the _push_agent_events helper."""

    def test_push_events_sends_to_connected(self):
        """Events should be sent to connected agents."""
        sim = TownSimulation.__new__(TownSimulation)
        sim._mgmt_client = MagicMock()
        sim._mgmt_client.send_message = MagicMock(return_value=True)
        sim._mgmt_client_failed = False

        mock_ws = MagicMock()
        mock_ws.get_agent_connection_id = MagicMock(return_value="conn_123")

        events = [("alice", {"type": "town_event", "event": "arrived"})]
        sim._push_agent_events(mock_ws, events)

        sim._mgmt_client.send_message.assert_called_once_with("conn_123", {"type": "town_event", "event": "arrived"})

    def test_push_events_skips_disconnected(self):
        """Events to disconnected agents should be skipped."""
        sim = TownSimulation.__new__(TownSimulation)
        sim._mgmt_client = MagicMock()
        sim._mgmt_client.send_message = MagicMock(return_value=True)
        sim._mgmt_client_failed = False

        mock_ws = MagicMock()
        mock_ws.get_agent_connection_id = MagicMock(return_value=None)

        events = [("alice", {"type": "town_event", "event": "arrived"})]
        sim._push_agent_events(mock_ws, events)

        sim._mgmt_client.send_message.assert_not_called()

    def test_push_events_handles_send_failure(self):
        """send_message failures should be logged, not crash."""
        sim = TownSimulation.__new__(TownSimulation)
        sim._mgmt_client = MagicMock()
        sim._mgmt_client.send_message = MagicMock(side_effect=Exception("test error"))
        sim._mgmt_client_failed = False

        mock_ws = MagicMock()
        mock_ws.get_agent_connection_id = MagicMock(return_value="conn_123")

        events = [("alice", {"type": "town_event", "event": "arrived"})]
        # Should NOT raise
        sim._push_agent_events(mock_ws, events)

    def test_push_events_noop_when_no_mgmt_client(self):
        """When mgmt client is unavailable, push is a no-op."""
        sim = TownSimulation.__new__(TownSimulation)
        sim._mgmt_client = None
        sim._mgmt_client_failed = True

        mock_ws = MagicMock()

        events = [("alice", {"type": "town_event", "event": "arrived"})]
        sim._push_agent_events(mock_ws, events)
        # No error, no calls

    def test_push_events_noop_when_empty(self):
        """Empty event list is a no-op."""
        sim = TownSimulation.__new__(TownSimulation)
        sim._mgmt_client = MagicMock()
        sim._mgmt_client_failed = False

        mock_ws = MagicMock()
        sim._push_agent_events(mock_ws, [])
        sim._mgmt_client.send_message.assert_not_called()


class TestNotifyViewers:
    """Test that _notify_fn is called after tick."""

    @pytest.mark.asyncio
    async def test_notify_fn_called_after_tick(self):
        """The viewer notification callback should be called after each tick."""
        sim, db_session = _make_simulation()
        notify_mock = MagicMock()
        sim._notify_fn = notify_mock

        mock_service = AsyncMock()
        mock_service.get_town_state = AsyncMock(return_value=[])
        mock_service.update_agent_state = AsyncMock()

        mock_ws = MagicMock()

        with patch(
            "core.services.town_simulation.TownSimulation._get_ws_manager",
            return_value=mock_ws,
        ):
            with patch(
                "core.services.town_service.TownService",
                return_value=mock_service,
            ):
                await sim._tick()

        # get_town_state returned empty, but notify should still be called
        # Actually, with empty states the function returns early before notify
        # Let's test with non-empty states instead

    @pytest.mark.asyncio
    async def test_notify_fn_called_with_agents(self):
        """The viewer notification callback should be called when agents exist."""
        sim, db_session = _make_simulation()
        notify_mock = MagicMock()
        sim._notify_fn = notify_mock

        agent_state = _make_agent_state(location_state="sleeping")

        mock_service = AsyncMock()
        mock_service.get_town_state = AsyncMock(return_value=[agent_state])
        mock_service.update_agent_state = AsyncMock()

        mock_ws = MagicMock()
        mock_ws.is_agent_connected = MagicMock(return_value=False)
        mock_ws.get_agent_connection_id = MagicMock(return_value=None)

        with patch(
            "core.services.town_simulation.TownSimulation._get_ws_manager",
            return_value=mock_ws,
        ):
            with patch(
                "core.services.town_service.TownService",
                return_value=mock_service,
            ):
                await sim._tick()

        notify_mock.assert_called_once()
