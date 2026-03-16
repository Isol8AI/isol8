"""
Tests for GooseTown real-time conversation mediation over WebSocket.

Tests the chat/say/end_conversation actions in the town_agent_act handler:
- Initiating a conversation (chat)
- Sending messages in a conversation (say)
- Ending a conversation (end_conversation)
- Busy agent rejection
- Relationship updates on conversation end

Uses mocked DB sessions, WsManager, and ManagementApiClient to isolate logic.
"""

import uuid
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from core.services.town_agent_ws import AgentConnection
from routers.websocket_chat import router


# ---- Helpers ---------------------------------------------------------------

AGENT_A_ID = str(uuid.uuid4())
AGENT_B_ID = str(uuid.uuid4())
INSTANCE_ID = str(uuid.uuid4())
CONN_A = "conn-agent-a"
CONN_B = "conn-agent-b"
CONV_ID = str(uuid.uuid4())


def _make_agent_conn(connection_id, agent_name, agent_id, user_id="user_1", instance_id=INSTANCE_ID):
    return AgentConnection(
        connection_id=connection_id,
        user_id=user_id,
        agent_name=agent_name,
        agent_id=agent_id,
        instance_id=instance_id,
    )


def _make_state_mock(agent_id, current_conversation_id=None, current_location="park"):
    state = MagicMock()
    state.agent_id = uuid.UUID(agent_id) if isinstance(agent_id, str) else agent_id
    state.current_conversation_id = current_conversation_id
    state.current_location = current_location
    state.current_activity = "idle"
    state.last_decision_at = None
    state.energy = 80
    state.mood = "0"
    return state


def _make_agent_mock(agent_id, traits=""):
    agent = MagicMock()
    agent.id = uuid.UUID(agent_id) if isinstance(agent_id, str) else agent_id
    agent.traits = traits
    return agent


def _make_scalar_one_result(value):
    """Create a mock for session.execute() that supports scalar_one()."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    result.scalar_one.return_value = value
    return result


def _make_conversation_mock(
    conv_id=None,
    participant_a_id=None,
    participant_b_id=None,
    status="active",
    public_log=None,
    turn_count=0,
):
    conv = MagicMock()
    conv.id = uuid.UUID(conv_id) if conv_id else uuid.uuid4()
    conv.participant_a_id = uuid.UUID(participant_a_id) if isinstance(participant_a_id, str) else participant_a_id
    conv.participant_b_id = uuid.UUID(participant_b_id) if isinstance(participant_b_id, str) else participant_b_id
    conv.status = status
    conv.public_log = public_log if public_log is not None else []
    conv.turn_count = turn_count
    conv.location = "park"
    conv.ended_at = None
    return conv


def _make_result_mock(scalar_value):
    """Create a mock for session.execute() return value."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar_value
    return result


class MockSession:
    """Async mock for SQLAlchemy session that can return different results
    for sequential execute() calls."""

    def __init__(self, execute_results=None):
        self._execute_results = list(execute_results or [])
        self._execute_call_count = 0
        self._added = []
        self.committed = False

    async def execute(self, stmt):
        if self._execute_call_count < len(self._execute_results):
            result = self._execute_results[self._execute_call_count]
            self._execute_call_count += 1
            return result
        # Return empty result by default
        return _make_result_mock(None)

    def add(self, obj):
        self._added.append(obj)

    async def flush(self):
        # Assign a UUID id to any added objects that need it
        for obj in self._added:
            if hasattr(obj, "id") and obj.id is None:
                obj.id = uuid.uuid4()

    async def commit(self):
        self.committed = True


@asynccontextmanager
async def _mock_session_ctx(mock_session):
    yield mock_session


# ---- Fixtures ---------------------------------------------------------------


@pytest.fixture
def test_app():
    app = FastAPI()
    app.include_router(router, prefix="/ws")
    return app


@pytest.fixture
def mock_connection_service():
    with patch("routers.websocket_chat.get_connection_service") as mock_getter:
        svc = MagicMock()
        svc.get_connection.return_value = {"user_id": "user_1", "org_id": None}
        mock_getter.return_value = svc
        yield svc


@pytest.fixture
def mock_management_api():
    with patch("routers.websocket_chat.get_management_api_client") as mock_getter:
        client = MagicMock()
        client.send_message = MagicMock(return_value=True)
        mock_getter.return_value = client
        yield client


@pytest.fixture(autouse=True)
def mock_gateway_pool():
    with patch("routers.websocket_chat.get_gateway_pool") as mock_getter:
        pool = MagicMock()
        mock_getter.return_value = pool
        yield pool


@pytest.fixture
def ws_manager():
    """A real TownAgentWsManager with two agents registered."""
    from core.services.town_agent_ws import TownAgentWsManager

    mgr = TownAgentWsManager()
    mgr.register(CONN_A, "user_1", "alice", AGENT_A_ID, INSTANCE_ID)
    mgr.register(CONN_B, "user_2", "bob", AGENT_B_ID, INSTANCE_ID)
    return mgr


async def _post_message(test_app, body, connection_id=CONN_A):
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        return await client.post(
            "/ws/message",
            headers={"x-connection-id": connection_id},
            json=body,
        )


# ---- Tests: Chat action (initiate conversation) ----------------------------


class TestChatAction:
    """Tests for action=chat in town_agent_act."""

    @pytest.mark.asyncio
    async def test_chat_initiates_conversation(
        self, test_app, mock_connection_service, mock_management_api, ws_manager
    ):
        """Chat action should create a conversation and push invite to target."""
        state_a = _make_state_mock(AGENT_A_ID)
        state_b = _make_state_mock(AGENT_B_ID)
        mock_session = MockSession(
            execute_results=[
                _make_result_mock(state_a),  # lookup initiator state
                _make_result_mock(state_b),  # lookup target state
            ]
        )

        with (
            patch("core.services.town_agent_ws.get_town_agent_ws_manager", return_value=ws_manager),
            patch("routers.websocket_chat.get_session_factory", return_value=lambda: _mock_session_ctx(mock_session)),
            patch("routers.town._push_to_viewers"),
        ):
            response = await _post_message(
                test_app,
                {
                    "type": "town_agent_act",
                    "action": "chat",
                    "target": "bob",
                    "message": "Hello Bob!",
                },
                connection_id=CONN_A,
            )

        assert response.status_code == 200

        # Should have sent invite to bob
        calls = mock_management_api.send_message.call_args_list
        invite_calls = [c for c in calls if c[0][0] == CONN_B and c[0][1].get("event") == "conversation_invite"]
        assert len(invite_calls) == 1
        invite_msg = invite_calls[0][0][1]
        assert invite_msg["from"] == "alice"
        assert invite_msg["message"] == "Hello Bob!"
        assert "conv_id" in invite_msg

        # Should have sent act_ok to initiator
        ok_calls = [c for c in calls if c[0][0] == CONN_A and c[0][1].get("event") == "act_ok"]
        assert len(ok_calls) == 1
        assert ok_calls[0][0][1]["action"] == "chat"

        # Both states should be updated
        assert state_a.current_activity == "chatting"
        assert state_a.current_conversation_id is not None
        assert state_b.current_activity == "chatting"
        assert state_b.current_conversation_id is not None

    @pytest.mark.asyncio
    async def test_chat_rejects_when_target_not_connected(
        self, test_app, mock_connection_service, mock_management_api, ws_manager
    ):
        """Chat should fail if target agent is not connected."""
        state_a = _make_state_mock(AGENT_A_ID)
        mock_session = MockSession(execute_results=[_make_result_mock(state_a)])

        # Unregister bob so he's not connected
        ws_manager.unregister(CONN_B)

        with (
            patch("core.services.town_agent_ws.get_town_agent_ws_manager", return_value=ws_manager),
            patch("routers.websocket_chat.get_session_factory", return_value=lambda: _mock_session_ctx(mock_session)),
        ):
            response = await _post_message(
                test_app,
                {
                    "type": "town_agent_act",
                    "action": "chat",
                    "target": "bob",
                    "message": "Hello?",
                },
            )

        assert response.status_code == 200
        calls = mock_management_api.send_message.call_args_list
        error_calls = [c for c in calls if c[0][1].get("event") == "error"]
        assert len(error_calls) == 1
        assert "not connected" in error_calls[0][0][1]["message"]

    @pytest.mark.asyncio
    async def test_chat_rejects_busy_target(self, test_app, mock_connection_service, mock_management_api, ws_manager):
        """Chat should return busy event if target is already in a conversation."""
        state_a = _make_state_mock(AGENT_A_ID)
        state_b = _make_state_mock(AGENT_B_ID, current_conversation_id=uuid.uuid4())
        mock_session = MockSession(
            execute_results=[
                _make_result_mock(state_a),
                _make_result_mock(state_b),
            ]
        )

        with (
            patch("core.services.town_agent_ws.get_town_agent_ws_manager", return_value=ws_manager),
            patch("routers.websocket_chat.get_session_factory", return_value=lambda: _mock_session_ctx(mock_session)),
        ):
            response = await _post_message(
                test_app,
                {
                    "type": "town_agent_act",
                    "action": "chat",
                    "target": "bob",
                    "message": "Hey!",
                },
            )

        assert response.status_code == 200
        calls = mock_management_api.send_message.call_args_list
        busy_calls = [c for c in calls if c[0][1].get("event") == "busy"]
        assert len(busy_calls) == 1
        assert busy_calls[0][0][1]["agent"] == "bob"

    @pytest.mark.asyncio
    async def test_chat_rejects_when_initiator_already_in_conversation(
        self, test_app, mock_connection_service, mock_management_api, ws_manager
    ):
        """Chat should fail if initiator is already in a conversation."""
        state_a = _make_state_mock(AGENT_A_ID, current_conversation_id=uuid.uuid4())
        mock_session = MockSession(execute_results=[_make_result_mock(state_a)])

        with (
            patch("core.services.town_agent_ws.get_town_agent_ws_manager", return_value=ws_manager),
            patch("routers.websocket_chat.get_session_factory", return_value=lambda: _mock_session_ctx(mock_session)),
        ):
            response = await _post_message(
                test_app,
                {
                    "type": "town_agent_act",
                    "action": "chat",
                    "target": "bob",
                    "message": "Hey!",
                },
            )

        assert response.status_code == 200
        calls = mock_management_api.send_message.call_args_list
        error_calls = [c for c in calls if c[0][1].get("event") == "error"]
        assert len(error_calls) == 1
        assert "already in a conversation" in error_calls[0][0][1]["message"].lower()

    @pytest.mark.asyncio
    async def test_chat_rejects_self_chat(self, test_app, mock_connection_service, mock_management_api, ws_manager):
        """Chat should fail if initiator tries to chat with themselves."""
        state_a = _make_state_mock(AGENT_A_ID)
        mock_session = MockSession(execute_results=[_make_result_mock(state_a)])

        with (
            patch("core.services.town_agent_ws.get_town_agent_ws_manager", return_value=ws_manager),
            patch("routers.websocket_chat.get_session_factory", return_value=lambda: _mock_session_ctx(mock_session)),
        ):
            response = await _post_message(
                test_app,
                {
                    "type": "town_agent_act",
                    "action": "chat",
                    "target": "alice",  # same as initiator
                    "message": "Talking to myself",
                },
            )

        assert response.status_code == 200
        calls = mock_management_api.send_message.call_args_list
        error_calls = [c for c in calls if c[0][1].get("event") == "error"]
        assert len(error_calls) == 1
        assert "yourself" in error_calls[0][0][1]["message"].lower()

    @pytest.mark.asyncio
    async def test_chat_missing_target(self, test_app, mock_connection_service, mock_management_api, ws_manager):
        """Chat should fail if target is not provided."""
        state_a = _make_state_mock(AGENT_A_ID)
        mock_session = MockSession(execute_results=[_make_result_mock(state_a)])

        with (
            patch("core.services.town_agent_ws.get_town_agent_ws_manager", return_value=ws_manager),
            patch("routers.websocket_chat.get_session_factory", return_value=lambda: _mock_session_ctx(mock_session)),
        ):
            response = await _post_message(
                test_app,
                {
                    "type": "town_agent_act",
                    "action": "chat",
                    "message": "Hello?",
                },
            )

        assert response.status_code == 200
        calls = mock_management_api.send_message.call_args_list
        error_calls = [c for c in calls if c[0][1].get("event") == "error"]
        assert len(error_calls) == 1
        assert "missing target" in error_calls[0][0][1]["message"].lower()


# ---- Tests: Say action (send message in conversation) -----------------------


class TestSayAction:
    """Tests for action=say in town_agent_act."""

    @pytest.mark.asyncio
    async def test_say_sends_message_to_partner(
        self, test_app, mock_connection_service, mock_management_api, ws_manager
    ):
        """Say action should append to log and push message to partner."""
        state_a = _make_state_mock(AGENT_A_ID, current_conversation_id=uuid.UUID(CONV_ID))
        conv = _make_conversation_mock(
            conv_id=CONV_ID,
            participant_a_id=AGENT_A_ID,
            participant_b_id=AGENT_B_ID,
            status="active",
            public_log=[],
            turn_count=0,
        )

        mock_session = MockSession(
            execute_results=[
                _make_result_mock(state_a),  # lookup initiator state
                _make_result_mock(conv),  # lookup conversation
            ]
        )

        with (
            patch("core.services.town_agent_ws.get_town_agent_ws_manager", return_value=ws_manager),
            patch("routers.websocket_chat.get_session_factory", return_value=lambda: _mock_session_ctx(mock_session)),
            patch("routers.town._push_to_viewers"),
        ):
            response = await _post_message(
                test_app,
                {
                    "type": "town_agent_act",
                    "action": "say",
                    "conv_id": CONV_ID,
                    "message": "Hey Bob, how are you?",
                },
            )

        assert response.status_code == 200

        # Verify message was pushed to bob
        calls = mock_management_api.send_message.call_args_list
        msg_calls = [c for c in calls if c[0][0] == CONN_B and c[0][1].get("event") == "conversation_message"]
        assert len(msg_calls) == 1
        msg = msg_calls[0][0][1]
        assert msg["from"] == "alice"
        assert msg["text"] == "Hey Bob, how are you?"
        assert msg["conv_id"] == CONV_ID
        assert msg["turn"] == 1

        # Verify log was appended
        assert conv.public_log == [{"speaker": "alice", "text": "Hey Bob, how are you?"}]
        assert conv.turn_count == 1

    @pytest.mark.asyncio
    async def test_say_rejects_non_participant(
        self, test_app, mock_connection_service, mock_management_api, ws_manager
    ):
        """Say should fail if agent is not a participant in the conversation."""
        other_a = str(uuid.uuid4())
        other_b = str(uuid.uuid4())
        state_a = _make_state_mock(AGENT_A_ID)
        conv = _make_conversation_mock(
            conv_id=CONV_ID,
            participant_a_id=other_a,
            participant_b_id=other_b,
            status="active",
        )

        mock_session = MockSession(execute_results=[_make_result_mock(state_a), _make_result_mock(conv)])

        with (
            patch("core.services.town_agent_ws.get_town_agent_ws_manager", return_value=ws_manager),
            patch("routers.websocket_chat.get_session_factory", return_value=lambda: _mock_session_ctx(mock_session)),
        ):
            response = await _post_message(
                test_app,
                {
                    "type": "town_agent_act",
                    "action": "say",
                    "conv_id": CONV_ID,
                    "message": "I shouldn't be here",
                },
            )

        assert response.status_code == 200
        calls = mock_management_api.send_message.call_args_list
        error_calls = [c for c in calls if c[0][1].get("event") == "error"]
        assert len(error_calls) == 1
        assert "not a participant" in error_calls[0][0][1]["message"].lower()

    @pytest.mark.asyncio
    async def test_say_rejects_ended_conversation(
        self, test_app, mock_connection_service, mock_management_api, ws_manager
    ):
        """Say should fail if conversation is not active."""
        state_a = _make_state_mock(AGENT_A_ID)
        conv = _make_conversation_mock(
            conv_id=CONV_ID,
            participant_a_id=AGENT_A_ID,
            participant_b_id=AGENT_B_ID,
            status="ended",
        )

        mock_session = MockSession(execute_results=[_make_result_mock(state_a), _make_result_mock(conv)])

        with (
            patch("core.services.town_agent_ws.get_town_agent_ws_manager", return_value=ws_manager),
            patch("routers.websocket_chat.get_session_factory", return_value=lambda: _mock_session_ctx(mock_session)),
        ):
            response = await _post_message(
                test_app,
                {
                    "type": "town_agent_act",
                    "action": "say",
                    "conv_id": CONV_ID,
                    "message": "Too late?",
                },
            )

        assert response.status_code == 200
        calls = mock_management_api.send_message.call_args_list
        error_calls = [c for c in calls if c[0][1].get("event") == "error"]
        assert len(error_calls) == 1
        assert "not active" in error_calls[0][0][1]["message"].lower()

    @pytest.mark.asyncio
    async def test_say_missing_conv_id(self, test_app, mock_connection_service, mock_management_api, ws_manager):
        """Say should fail if conv_id is not provided."""
        state_a = _make_state_mock(AGENT_A_ID)
        mock_session = MockSession(execute_results=[_make_result_mock(state_a)])

        with (
            patch("core.services.town_agent_ws.get_town_agent_ws_manager", return_value=ws_manager),
            patch("routers.websocket_chat.get_session_factory", return_value=lambda: _mock_session_ctx(mock_session)),
        ):
            response = await _post_message(
                test_app,
                {
                    "type": "town_agent_act",
                    "action": "say",
                    "message": "No conv_id",
                },
            )

        assert response.status_code == 200
        calls = mock_management_api.send_message.call_args_list
        error_calls = [c for c in calls if c[0][1].get("event") == "error"]
        assert len(error_calls) == 1
        assert "missing conv_id" in error_calls[0][0][1]["message"].lower()

    @pytest.mark.asyncio
    async def test_say_auto_ends_at_max_turns(self, test_app, mock_connection_service, mock_management_api, ws_manager):
        """Say should auto-end conversation when max turns (10) is reached."""
        state_a = _make_state_mock(AGENT_A_ID, current_conversation_id=uuid.UUID(CONV_ID))
        state_b = _make_state_mock(AGENT_B_ID, current_conversation_id=uuid.UUID(CONV_ID))

        # Conversation already has 9 turns, this will be the 10th
        existing_log = [{"speaker": "alice" if i % 2 == 0 else "bob", "text": f"msg {i}"} for i in range(9)]
        conv = _make_conversation_mock(
            conv_id=CONV_ID,
            participant_a_id=AGENT_A_ID,
            participant_b_id=AGENT_B_ID,
            status="active",
            public_log=existing_log,
            turn_count=9,
        )

        # Mock relationship
        rel_mock = MagicMock()
        rel_mock.id = uuid.uuid4()
        rel_mock.affinity_score = 0
        rel_mock.interaction_count = 0
        rel_result = MagicMock()
        rel_result.scalar_one_or_none.return_value = rel_mock

        # For update_relationship, need scalar_one
        rel_update_result = MagicMock()
        rel_update_result.scalar_one.return_value = rel_mock

        mock_session = MockSession(
            execute_results=[
                _make_result_mock(state_a),  # lookup initiator state
                _make_result_mock(conv),  # lookup conversation
                _make_result_mock(state_b),  # lookup partner state (auto-end)
                rel_result,  # get_or_create_relationship select
                rel_update_result,  # update_relationship select
            ]
        )

        with (
            patch("core.services.town_agent_ws.get_town_agent_ws_manager", return_value=ws_manager),
            patch("routers.websocket_chat.get_session_factory", return_value=lambda: _mock_session_ctx(mock_session)),
            patch("routers.town._push_to_viewers"),
        ):
            response = await _post_message(
                test_app,
                {
                    "type": "town_agent_act",
                    "action": "say",
                    "conv_id": CONV_ID,
                    "message": "This is the 10th message",
                },
            )

        assert response.status_code == 200

        # Conversation should be ended
        assert conv.status == "ended"
        assert conv.ended_at is not None
        assert conv.turn_count == 10

        # Both states should be cleared
        assert state_a.current_conversation_id is None
        assert state_a.current_activity == "idle"
        assert state_b.current_conversation_id is None
        assert state_b.current_activity == "idle"

        # Partner should receive conversation_ended event
        calls = mock_management_api.send_message.call_args_list
        end_calls = [c for c in calls if c[0][0] == CONN_B and c[0][1].get("event") == "conversation_ended"]
        assert len(end_calls) == 1
        assert end_calls[0][0][1]["reason"] == "max_turns"


# ---- Tests: End conversation action -----------------------------------------


class TestEndConversationAction:
    """Tests for action=end_conversation in town_agent_act."""

    @pytest.mark.asyncio
    async def test_end_conversation_success(self, test_app, mock_connection_service, mock_management_api, ws_manager):
        """End conversation should set status=ended, clear states, update relationship."""
        state_a = _make_state_mock(AGENT_A_ID, current_conversation_id=uuid.UUID(CONV_ID))
        state_b = _make_state_mock(AGENT_B_ID, current_conversation_id=uuid.UUID(CONV_ID))

        conv = _make_conversation_mock(
            conv_id=CONV_ID,
            participant_a_id=AGENT_A_ID,
            participant_b_id=AGENT_B_ID,
            status="active",
            public_log=[{"speaker": "alice", "text": "hi"}, {"speaker": "bob", "text": "hello"}],
            turn_count=2,
        )

        # Mock relationship
        rel_mock = MagicMock()
        rel_mock.id = uuid.uuid4()
        rel_mock.affinity_score = 0
        rel_mock.interaction_count = 0
        rel_result = MagicMock()
        rel_result.scalar_one_or_none.return_value = rel_mock

        rel_update_result = MagicMock()
        rel_update_result.scalar_one.return_value = rel_mock

        # Mock TownAgent lookups for mood/energy wiring
        agent_a_mock = _make_agent_mock(AGENT_A_ID)
        agent_b_mock = _make_agent_mock(AGENT_B_ID)

        mock_session = MockSession(
            execute_results=[
                _make_result_mock(state_a),  # lookup initiator state
                _make_result_mock(conv),  # lookup conversation
                _make_result_mock(state_b),  # lookup partner state
                rel_result,  # get_or_create_relationship
                rel_update_result,  # update_relationship
                _make_scalar_one_result(agent_a_mock),  # TownAgent lookup for initiator (mood)
                _make_scalar_one_result(agent_b_mock),  # TownAgent lookup for partner (mood)
            ]
        )

        with (
            patch("core.services.town_agent_ws.get_town_agent_ws_manager", return_value=ws_manager),
            patch("routers.websocket_chat.get_session_factory", return_value=lambda: _mock_session_ctx(mock_session)),
            patch("routers.town._push_to_viewers"),
        ):
            response = await _post_message(
                test_app,
                {
                    "type": "town_agent_act",
                    "action": "end_conversation",
                    "conv_id": CONV_ID,
                },
            )

        assert response.status_code == 200

        # Conversation should be ended
        assert conv.status == "ended"
        assert conv.ended_at is not None

        # Both states should be cleared
        assert state_a.current_conversation_id is None
        assert state_a.current_activity == "idle"
        assert state_b.current_conversation_id is None
        assert state_b.current_activity == "idle"

        # Partner should receive conversation_ended event
        calls = mock_management_api.send_message.call_args_list
        end_calls = [c for c in calls if c[0][0] == CONN_B and c[0][1].get("event") == "conversation_ended"]
        assert len(end_calls) == 1
        assert end_calls[0][0][1]["conv_id"] == CONV_ID

        # Initiator should receive act_ok
        ok_calls = [c for c in calls if c[0][0] == CONN_A and c[0][1].get("event") == "act_ok"]
        assert len(ok_calls) == 1

    @pytest.mark.asyncio
    async def test_end_conversation_updates_relationship(
        self, test_app, mock_connection_service, mock_management_api, ws_manager
    ):
        """End conversation should bump affinity and interaction count."""
        state_a = _make_state_mock(AGENT_A_ID, current_conversation_id=uuid.UUID(CONV_ID))
        state_b = _make_state_mock(AGENT_B_ID, current_conversation_id=uuid.UUID(CONV_ID))
        conv = _make_conversation_mock(
            conv_id=CONV_ID,
            participant_a_id=AGENT_A_ID,
            participant_b_id=AGENT_B_ID,
            status="active",
        )

        rel_mock = MagicMock()
        rel_mock.id = uuid.uuid4()
        rel_mock.affinity_score = 5
        rel_mock.interaction_count = 3
        rel_mock.last_interaction_at = None
        rel_result = MagicMock()
        rel_result.scalar_one_or_none.return_value = rel_mock

        rel_update_result = MagicMock()
        rel_update_result.scalar_one.return_value = rel_mock

        # Mock TownAgent lookups for mood/energy wiring
        agent_a_mock = _make_agent_mock(AGENT_A_ID)
        agent_b_mock = _make_agent_mock(AGENT_B_ID)

        mock_session = MockSession(
            execute_results=[
                _make_result_mock(state_a),
                _make_result_mock(conv),
                _make_result_mock(state_b),
                rel_result,
                rel_update_result,
                _make_scalar_one_result(agent_a_mock),  # TownAgent lookup for initiator (mood)
                _make_scalar_one_result(agent_b_mock),  # TownAgent lookup for partner (mood)
            ]
        )

        with (
            patch("core.services.town_agent_ws.get_town_agent_ws_manager", return_value=ws_manager),
            patch("routers.websocket_chat.get_session_factory", return_value=lambda: _mock_session_ctx(mock_session)),
            patch("routers.town._push_to_viewers"),
        ):
            response = await _post_message(
                test_app,
                {
                    "type": "town_agent_act",
                    "action": "end_conversation",
                    "conv_id": CONV_ID,
                },
            )

        assert response.status_code == 200

        # Relationship should have been updated: affinity +1, interaction_count +1
        assert rel_mock.affinity_score == 6
        assert rel_mock.interaction_count == 4
        assert rel_mock.last_interaction_at is not None

    @pytest.mark.asyncio
    async def test_end_conversation_not_found(self, test_app, mock_connection_service, mock_management_api, ws_manager):
        """End conversation should fail if conversation not found."""
        state_a = _make_state_mock(AGENT_A_ID)
        mock_session = MockSession(
            execute_results=[
                _make_result_mock(state_a),
                _make_result_mock(None),  # conversation not found
            ]
        )

        with (
            patch("core.services.town_agent_ws.get_town_agent_ws_manager", return_value=ws_manager),
            patch("routers.websocket_chat.get_session_factory", return_value=lambda: _mock_session_ctx(mock_session)),
        ):
            response = await _post_message(
                test_app,
                {
                    "type": "town_agent_act",
                    "action": "end_conversation",
                    "conv_id": CONV_ID,
                },
            )

        assert response.status_code == 200
        calls = mock_management_api.send_message.call_args_list
        error_calls = [c for c in calls if c[0][1].get("event") == "error"]
        assert len(error_calls) == 1
        assert "not found" in error_calls[0][0][1]["message"].lower()

    @pytest.mark.asyncio
    async def test_end_conversation_non_participant(
        self, test_app, mock_connection_service, mock_management_api, ws_manager
    ):
        """End conversation should fail if agent is not a participant."""
        other_a = str(uuid.uuid4())
        other_b = str(uuid.uuid4())
        state_a = _make_state_mock(AGENT_A_ID)
        conv = _make_conversation_mock(
            conv_id=CONV_ID,
            participant_a_id=other_a,
            participant_b_id=other_b,
            status="active",
        )

        mock_session = MockSession(execute_results=[_make_result_mock(state_a), _make_result_mock(conv)])

        with (
            patch("core.services.town_agent_ws.get_town_agent_ws_manager", return_value=ws_manager),
            patch("routers.websocket_chat.get_session_factory", return_value=lambda: _mock_session_ctx(mock_session)),
        ):
            response = await _post_message(
                test_app,
                {
                    "type": "town_agent_act",
                    "action": "end_conversation",
                    "conv_id": CONV_ID,
                },
            )

        assert response.status_code == 200
        calls = mock_management_api.send_message.call_args_list
        error_calls = [c for c in calls if c[0][1].get("event") == "error"]
        assert len(error_calls) == 1
        assert "not a participant" in error_calls[0][0][1]["message"].lower()

    @pytest.mark.asyncio
    async def test_end_conversation_missing_conv_id(
        self, test_app, mock_connection_service, mock_management_api, ws_manager
    ):
        """End conversation should fail if conv_id is not provided."""
        state_a = _make_state_mock(AGENT_A_ID)
        mock_session = MockSession(execute_results=[_make_result_mock(state_a)])

        with (
            patch("core.services.town_agent_ws.get_town_agent_ws_manager", return_value=ws_manager),
            patch("routers.websocket_chat.get_session_factory", return_value=lambda: _mock_session_ctx(mock_session)),
        ):
            response = await _post_message(
                test_app,
                {
                    "type": "town_agent_act",
                    "action": "end_conversation",
                },
            )

        assert response.status_code == 200
        calls = mock_management_api.send_message.call_args_list
        error_calls = [c for c in calls if c[0][1].get("event") == "error"]
        assert len(error_calls) == 1
        assert "missing conv_id" in error_calls[0][0][1]["message"].lower()


# ---- Tests: Full conversation flow ------------------------------------------


class TestConversationFlow:
    """End-to-end tests for a full conversation: chat -> say -> end."""

    @pytest.mark.asyncio
    async def test_viewer_push_on_conversation_events(
        self, test_app, mock_connection_service, mock_management_api, ws_manager
    ):
        """Viewer push should be called for conversation_started event."""
        state_a = _make_state_mock(AGENT_A_ID)
        state_b = _make_state_mock(AGENT_B_ID)
        mock_session = MockSession(
            execute_results=[
                _make_result_mock(state_a),
                _make_result_mock(state_b),
            ]
        )

        with (
            patch("core.services.town_agent_ws.get_town_agent_ws_manager", return_value=ws_manager),
            patch("routers.websocket_chat.get_session_factory", return_value=lambda: _mock_session_ctx(mock_session)),
            patch("routers.town._push_to_viewers") as mock_push,
        ):
            response = await _post_message(
                test_app,
                {
                    "type": "town_agent_act",
                    "action": "chat",
                    "target": "bob",
                    "message": "Hello!",
                },
            )

        assert response.status_code == 200
        # _push_to_viewers should have been called with conversation_started
        mock_push.assert_called_once()
        viewer_msg = mock_push.call_args[0][0]
        assert viewer_msg["event"] == "conversation_started"
        assert "alice" in viewer_msg["participants"]
        assert "bob" in viewer_msg["participants"]

    @pytest.mark.asyncio
    async def test_not_connected_agent_returns_error(self, test_app, mock_connection_service, mock_management_api):
        """town_agent_act from a non-registered connection should return error."""
        from core.services.town_agent_ws import TownAgentWsManager

        empty_manager = TownAgentWsManager()

        with (
            patch("core.services.town_agent_ws.get_town_agent_ws_manager", return_value=empty_manager),
        ):
            response = await _post_message(
                test_app,
                {
                    "type": "town_agent_act",
                    "action": "chat",
                    "target": "bob",
                    "message": "Hello!",
                },
            )

        assert response.status_code == 200
        calls = mock_management_api.send_message.call_args_list
        error_calls = [c for c in calls if c[0][1].get("event") == "error"]
        assert len(error_calls) == 1
        assert "not connected" in error_calls[0][0][1]["message"].lower()
