# backend/tests/unit/core/test_chat_event_transform.py
"""Unit tests for GatewayConnection.

Covers _transform_chat_event() and is_connected property.
"""

import pytest
from unittest.mock import MagicMock

from core.gateway.connection_pool import GatewayConnection


class TestIsConnected:
    """Tests for is_connected property (websockets v16 compat)."""

    def _make_conn(self):
        return GatewayConnection(
            user_id="test-user",
            ip="10.0.0.1",
            token="t",
            management_api=MagicMock(),
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


class TestTransformChatEvent:
    """Tests for _transform_chat_event (computes incremental deltas from cumulative text)."""

    def _make_conn(self):
        return GatewayConnection(
            user_id="u",
            ip="0.0.0.0",
            token="t",
            management_api=MagicMock(),
        )

    def test_cumulative_text_produces_incremental_deltas(self):
        """Successive cumulative text blocks should yield only the new portion."""
        conn = self._make_conn()
        r1 = conn._transform_chat_event(
            "chat",
            {"state": "delta", "message": {"content": [{"type": "text", "text": "Hello"}]}},
        )
        assert r1 == {"type": "chunk", "content": "Hello"}

        r2 = conn._transform_chat_event(
            "chat",
            {"state": "delta", "message": {"content": [{"type": "text", "text": "Hello world"}]}},
        )
        assert r2 == {"type": "chunk", "content": " world"}

    def test_final_resets_tracking(self):
        """After final, the next turn starts fresh."""
        conn = self._make_conn()
        conn._transform_chat_event(
            "chat",
            {"state": "delta", "message": {"content": [{"type": "text", "text": "Hi"}]}},
        )
        conn._transform_chat_event("chat", {"state": "final"})

        r = conn._transform_chat_event(
            "chat",
            {"state": "delta", "message": {"content": [{"type": "text", "text": "New turn"}]}},
        )
        assert r == {"type": "chunk", "content": "New turn"}

    def test_chat_delta_with_string_content(self):
        conn = self._make_conn()
        result = conn._transform_chat_event("chat", {"state": "delta", "message": {"content": "Hello"}})
        assert result == {"type": "chunk", "content": "Hello"}

    def test_chat_delta_with_string_message(self):
        conn = self._make_conn()
        result = conn._transform_chat_event("chat", {"state": "delta", "message": "Hi there"})
        assert result == {"type": "chunk", "content": "Hi there"}

    def test_chat_delta_empty_message(self):
        conn = self._make_conn()
        assert conn._transform_chat_event("chat", {"state": "delta", "message": {}}) is None
        assert conn._transform_chat_event("chat", {"state": "delta"}) is None
        assert conn._transform_chat_event("chat", {"state": "delta", "message": {"content": []}}) is None

    def test_chat_final(self):
        conn = self._make_conn()
        result = conn._transform_chat_event("chat", {"state": "final"})
        assert result == {"type": "done"}

    def test_chat_error_with_dict(self):
        conn = self._make_conn()
        result = conn._transform_chat_event("chat", {"state": "error", "error": {"message": "Rate limited"}})
        assert result == {"type": "error", "message": "Rate limited"}

    def test_chat_error_with_string(self):
        conn = self._make_conn()
        result = conn._transform_chat_event("chat", {"state": "error", "error": "Something broke"})
        assert result == {"type": "error", "message": "Something broke"}

    def test_chat_aborted(self):
        conn = self._make_conn()
        result = conn._transform_chat_event("chat", {"state": "aborted"})
        assert result == {"type": "error", "message": "Agent run was cancelled"}

    def test_chat_unknown_state(self):
        conn = self._make_conn()
        assert conn._transform_chat_event("chat", {"state": "unknown"}) is None

    def test_non_chat_event_returns_none(self):
        conn = self._make_conn()
        assert conn._transform_chat_event("text_delta", {"delta": "Hi"}) is None
        assert conn._transform_chat_event("unknown_event", {}) is None


class TestHandleMessageChatEvents:
    """Tests that _handle_message correctly routes chat events through transformation."""

    @pytest.fixture
    def mock_management_api(self):
        from unittest.mock import MagicMock

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
        )
        conn._frontend_connections.add("conn-1")
        return conn

    def test_chat_event_transformed_before_forwarding(self, connection, mock_management_api):
        """Chat events should be transformed, not forwarded raw."""
        connection._handle_message(
            {
                "type": "event",
                "event": "chat",
                "payload": {"state": "delta", "message": {"content": [{"type": "text", "text": "Hi!"}]}},
            }
        )
        mock_management_api.send_message.assert_called_once_with("conn-1", {"type": "chunk", "content": "Hi!"})

    def test_non_chat_event_forwarded_as_is(self, connection, mock_management_api):
        """Non-chat events should be forwarded raw for SWR revalidation."""
        raw_event = {"type": "event", "event": "health", "payload": {"status": "ok"}}
        connection._handle_message(raw_event)
        mock_management_api.send_message.assert_called_once_with("conn-1", raw_event)

    def test_skipped_chat_event_not_forwarded(self, connection, mock_management_api):
        """Events that transform to None should not be forwarded."""
        connection._handle_message(
            {
                "type": "event",
                "event": "chat",
                "payload": {"state": "unknown"},
            }
        )
        mock_management_api.send_message.assert_not_called()

    def test_chat_final_sends_done(self, connection, mock_management_api):
        connection._handle_message(
            {
                "type": "event",
                "event": "chat",
                "payload": {"state": "final"},
            }
        )
        mock_management_api.send_message.assert_called_once_with("conn-1", {"type": "done"})

    def test_chat_events_sent_to_all_frontend_connections(self, connection, mock_management_api):
        """Chat events should be forwarded to all registered frontend connections."""
        connection._frontend_connections.add("conn-2")
        connection._handle_message(
            {
                "type": "event",
                "event": "chat",
                "payload": {"state": "delta", "message": {"content": "chunk"}},
            }
        )
        assert mock_management_api.send_message.call_count == 2
