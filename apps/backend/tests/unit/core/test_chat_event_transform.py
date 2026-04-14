# backend/tests/unit/core/test_chat_event_transform.py
"""Unit tests for GatewayConnection.

Covers _transform_agent_event(), _handle_message routing, and is_connected property.
"""

import pytest
from unittest.mock import MagicMock, call

from core.gateway.connection_pool import GatewayConnection


class TestIsConnected:
    """Tests for is_connected property (websockets v16 compat)."""

    def _make_conn(self):

        return GatewayConnection(
            user_id="test-user",
            ip="10.0.0.1",
            token="t",
            management_api=MagicMock(),
            frontend_connections=set(),
            conn_member_map={},
        )

    def test_no_ws_returns_false(self):
        conn = self._make_conn()
        assert conn.is_connected is False

    def test_ws_with_state_open(self):
        from websockets.protocol import State

        conn = self._make_conn()
        ws = MagicMock()
        ws.state = State.OPEN
        conn._ws = ws
        assert conn.is_connected is True

    def test_ws_with_state_closed(self):
        from websockets.protocol import State

        conn = self._make_conn()
        ws = MagicMock()
        ws.state = State.CLOSED
        conn._ws = ws
        assert conn.is_connected is False

    def test_ws_without_state_uses_closed_fallback(self):
        """Fallback for older websockets versions that have .closed attribute."""
        conn = self._make_conn()
        ws = MagicMock(spec=[])  # No attributes by default
        ws.closed = False
        del ws.state  # Ensure no .state
        conn._ws = ws
        assert conn.is_connected is True


class TestTransformAgentEvent:
    """Tests for _transform_agent_event.

    OpenClaw agent events fire for every LLM token (unthrottled).
    Only assistant-stream events with cumulative text are forwarded.
    """

    def test_assistant_stream_with_text(self):
        result = GatewayConnection._transform_agent_event(
            {"stream": "assistant", "data": {"text": "Hello", "delta": "o"}}
        )
        assert result == {"type": "chunk", "content": "Hello"}

    def test_assistant_stream_cumulative(self):
        """Successive events carry progressively longer cumulative text."""
        r1 = GatewayConnection._transform_agent_event({"stream": "assistant", "data": {"text": "He", "delta": "He"}})
        assert r1 == {"type": "chunk", "content": "He"}

        r2 = GatewayConnection._transform_agent_event(
            {"stream": "assistant", "data": {"text": "Hello world", "delta": "llo world"}}
        )
        assert r2 == {"type": "chunk", "content": "Hello world"}

    def test_non_assistant_non_tool_stream_ignored(self):
        assert GatewayConnection._transform_agent_event({"stream": "lifecycle", "data": {"phase": "start"}}) is None
        assert GatewayConnection._transform_agent_event({"stream": "compaction", "data": {"phase": "start"}}) is None

    def test_tool_stream_start_phase(self):
        result = GatewayConnection._transform_agent_event(
            {"stream": "tool", "data": {"name": "web_search", "phase": "start", "toolCallId": "abc-123"}}
        )
        assert result == {"type": "tool_start", "tool": "web_search", "toolCallId": "abc-123"}

    def test_tool_stream_result_phase(self):
        result = GatewayConnection._transform_agent_event(
            {"stream": "tool", "data": {"name": "web_search", "phase": "result", "toolCallId": "abc-123"}}
        )
        assert result == {"type": "tool_end", "tool": "web_search", "toolCallId": "abc-123"}

    def test_tool_stream_result_with_is_error(self):
        """OpenClaw signals tool errors via isError on the result phase."""
        result = GatewayConnection._transform_agent_event(
            {
                "stream": "tool",
                "data": {"name": "web_search", "phase": "result", "toolCallId": "abc-123", "isError": True},
            }
        )
        assert result == {"type": "tool_error", "tool": "web_search", "toolCallId": "abc-123"}

    def test_tool_stream_update_phase_ignored(self):
        """Intermediate tool updates are not forwarded."""
        result = GatewayConnection._transform_agent_event(
            {"stream": "tool", "data": {"name": "web_search", "phase": "update", "toolCallId": "abc-123"}}
        )
        assert result is None

    def test_tool_stream_missing_name_ignored(self):
        result = GatewayConnection._transform_agent_event(
            {"stream": "tool", "data": {"phase": "start", "toolCallId": "abc-123"}}
        )
        assert result is None

    def test_thinking_stream_with_text(self):
        result = GatewayConnection._transform_agent_event(
            {"stream": "thinking", "data": {"text": "Let me think...", "delta": "..."}}
        )
        assert result == {"type": "thinking", "content": "Let me think..."}

    def test_reasoning_stream_with_text(self):
        """OpenClaw may emit reasoning events under either stream name."""
        result = GatewayConnection._transform_agent_event(
            {"stream": "reasoning", "data": {"text": "Considering options", "delta": "s"}}
        )
        assert result == {"type": "thinking", "content": "Considering options"}

    def test_thinking_stream_empty_text_ignored(self):
        assert GatewayConnection._transform_agent_event({"stream": "thinking", "data": {"text": ""}}) is None

    def test_missing_stream_ignored(self):
        assert GatewayConnection._transform_agent_event({"data": {"text": "Hi"}}) is None

    def test_missing_data_ignored(self):
        assert GatewayConnection._transform_agent_event({"stream": "assistant"}) is None

    def test_non_dict_data_ignored(self):
        assert GatewayConnection._transform_agent_event({"stream": "assistant", "data": "string"}) is None

    def test_empty_text_ignored(self):
        assert (
            GatewayConnection._transform_agent_event({"stream": "assistant", "data": {"text": "", "delta": ""}}) is None
        )


class TestHandleMessage:
    """Tests that _handle_message routes events correctly.

    - Agent events → smooth streaming via _transform_agent_event
    - Chat events → only terminal states (final sends complete text + done)
    - Chat delta → skipped (agent events handle streaming)
    - Other events → forwarded as-is
    """

    @pytest.fixture
    def mock_management_api(self):
        client = MagicMock()
        client.send_message = MagicMock(return_value=True)
        return client

    @pytest.fixture
    def connection(self, mock_management_api):

        conn = GatewayConnection(
            user_id="test-user",
            ip="10.0.0.1",
            token="test-token",
            management_api=mock_management_api,
            frontend_connections=set(),
            conn_member_map={},
        )
        conn._frontend_connections.add("conn-1")
        return conn

    # -- Agent events (unthrottled streaming) --

    def test_agent_assistant_event_forwarded_as_chunk(self, connection, mock_management_api):
        connection._handle_message(
            {
                "type": "event",
                "event": "agent",
                "payload": {"stream": "assistant", "data": {"text": "Hello", "delta": "o"}},
            }
        )
        mock_management_api.send_message.assert_called_once_with("conn-1", {"type": "chunk", "content": "Hello"})

    def test_agent_non_assistant_event_skipped(self, connection, mock_management_api):
        connection._handle_message(
            {
                "type": "event",
                "event": "agent",
                "payload": {"stream": "lifecycle", "data": {"phase": "start"}},
            }
        )
        mock_management_api.send_message.assert_not_called()

    def test_agent_tool_start_forwarded(self, connection, mock_management_api):
        connection._handle_message(
            {
                "type": "event",
                "event": "agent",
                "payload": {"stream": "tool", "data": {"name": "web_search", "phase": "start", "toolCallId": "t1"}},
            }
        )
        mock_management_api.send_message.assert_called_once_with(
            "conn-1", {"type": "tool_start", "tool": "web_search", "toolCallId": "t1"}
        )

    def test_agent_tool_end_forwarded(self, connection, mock_management_api):
        connection._handle_message(
            {
                "type": "event",
                "event": "agent",
                "payload": {"stream": "tool", "data": {"name": "web_search", "phase": "result", "toolCallId": "t1"}},
            }
        )
        mock_management_api.send_message.assert_called_once_with(
            "conn-1", {"type": "tool_end", "tool": "web_search", "toolCallId": "t1"}
        )

    def test_agent_events_tagged_with_agent_id_from_session_key(self, connection, mock_management_api):
        """sessionKey in the payload populates agent_id so the frontend can filter cross-agent messages."""
        connection._handle_message(
            {
                "type": "event",
                "event": "agent",
                "payload": {
                    "stream": "assistant",
                    "data": {"text": "Hello"},
                    "sessionKey": "agent:my-agent-id:main",
                },
            }
        )
        mock_management_api.send_message.assert_called_once_with(
            "conn-1", {"type": "chunk", "content": "Hello", "agent_id": "my-agent-id"}
        )

    def test_chat_final_tagged_with_agent_id(self, connection, mock_management_api):
        """chat.final done signal carries agent_id so the frontend can route it."""
        connection._handle_message(
            {
                "type": "event",
                "event": "chat",
                "payload": {
                    "state": "final",
                    "sessionKey": "agent:my-agent-id:main",
                    "message": {"role": "assistant", "content": [{"type": "text", "text": "Done."}]},
                },
            }
        )
        mock_management_api.send_message.assert_called_once_with("conn-1", {"type": "done", "agent_id": "my-agent-id"})

    # -- Chat events (terminal states only) --

    def test_chat_delta_skipped(self, connection, mock_management_api):
        """Chat delta events are ignored — agent events handle streaming."""
        connection._handle_message(
            {
                "type": "event",
                "event": "chat",
                "payload": {
                    "state": "delta",
                    "message": {"content": [{"type": "text", "text": "Hi!"}]},
                },
            }
        )
        mock_management_api.send_message.assert_not_called()

    def test_chat_final_sends_only_done(self, connection, mock_management_api):
        """Final sends just the done signal — assistant text streamed via agent events."""
        connection._handle_message(
            {
                "type": "event",
                "event": "chat",
                "payload": {
                    "state": "final",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "Complete response here."}],
                    },
                },
            }
        )
        mock_management_api.send_message.assert_called_once_with("conn-1", {"type": "done"})

    def test_chat_final_with_thinking_sends_thinking_then_done(self, connection, mock_management_api):
        """Thinking blocks in the final message are forwarded for models that batch reasoning."""
        connection._handle_message(
            {
                "type": "event",
                "event": "chat",
                "payload": {
                    "state": "final",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "thinking", "thinking": "Let me reason about this..."},
                            {"type": "text", "text": "Answer"},
                        ],
                    },
                },
            }
        )
        assert mock_management_api.send_message.call_count == 2
        calls = mock_management_api.send_message.call_args_list
        assert calls[0] == call("conn-1", {"type": "thinking", "content": "Let me reason about this..."})
        assert calls[1] == call("conn-1", {"type": "done"})

    def test_chat_final_without_text_sends_only_done(self, connection, mock_management_api):
        connection._handle_message(
            {
                "type": "event",
                "event": "chat",
                "payload": {"state": "final"},
            }
        )
        mock_management_api.send_message.assert_called_once_with("conn-1", {"type": "done"})

    def test_chat_error_with_dict(self, connection, mock_management_api):
        connection._handle_message(
            {
                "type": "event",
                "event": "chat",
                "payload": {"state": "error", "error": {"message": "Rate limited"}},
            }
        )
        mock_management_api.send_message.assert_called_once_with("conn-1", {"type": "error", "message": "Rate limited"})

    def test_chat_error_with_string(self, connection, mock_management_api):
        connection._handle_message(
            {
                "type": "event",
                "event": "chat",
                "payload": {"state": "error", "error": "Something broke"},
            }
        )
        mock_management_api.send_message.assert_called_once_with(
            "conn-1", {"type": "error", "message": "Something broke"}
        )

    def test_chat_aborted(self, connection, mock_management_api):
        connection._handle_message(
            {
                "type": "event",
                "event": "chat",
                "payload": {"state": "aborted"},
            }
        )
        mock_management_api.send_message.assert_called_once_with(
            "conn-1", {"type": "error", "message": "Agent run was cancelled"}
        )

    def test_chat_unknown_state_skipped(self, connection, mock_management_api):
        connection._handle_message(
            {
                "type": "event",
                "event": "chat",
                "payload": {"state": "unknown"},
            }
        )
        mock_management_api.send_message.assert_not_called()

    # -- Other events (forwarded as-is) --

    def test_non_chat_non_agent_event_forwarded_as_is(self, connection, mock_management_api):
        raw_event = {"type": "event", "event": "sessions.updated", "payload": {"status": "ok"}}
        connection._handle_message(raw_event)
        mock_management_api.send_message.assert_called_once_with("conn-1", raw_event)

    def test_health_tick_events_dropped(self, connection, mock_management_api):
        """Health/tick heartbeat events should never reach frontends."""
        connection._handle_message({"type": "event", "event": "health", "payload": {}})
        connection._handle_message({"type": "event", "event": "tick", "payload": {}})
        mock_management_api.send_message.assert_not_called()

    # -- Multi-connection forwarding --

    def test_events_sent_to_all_frontend_connections(self, connection, mock_management_api):
        connection._frontend_connections.add("conn-2")
        connection._handle_message(
            {
                "type": "event",
                "event": "agent",
                "payload": {"stream": "assistant", "data": {"text": "Hi"}},
            }
        )
        assert mock_management_api.send_message.call_count == 2
