# backend/tests/unit/core/test_chat_event_transform.py
"""Unit tests for GatewayConnection._transform_chat_event().

Verifies that OpenClaw chat events are correctly transformed into
the frontend's chunk/done/error/heartbeat message format.
"""

import pytest

from core.gateway.connection_pool import GatewayConnection


class TestTransformChatEvent:
    """Tests for _transform_chat_event static method."""

    def test_text_delta_with_delta_field(self):
        result = GatewayConnection._transform_chat_event("text_delta", {"delta": "Hello "})
        assert result == {"type": "chunk", "content": "Hello "}

    def test_text_delta_with_content_field(self):
        result = GatewayConnection._transform_chat_event("text_delta", {"content": "world"})
        assert result == {"type": "chunk", "content": "world"}

    def test_text_delta_prefers_delta_over_content(self):
        result = GatewayConnection._transform_chat_event("text_delta", {"delta": "preferred", "content": "fallback"})
        assert result == {"type": "chunk", "content": "preferred"}

    def test_text_delta_empty_content_returns_none(self):
        assert GatewayConnection._transform_chat_event("text_delta", {}) is None
        assert GatewayConnection._transform_chat_event("text_delta", {"delta": ""}) is None
        assert GatewayConnection._transform_chat_event("text_delta", {"content": ""}) is None

    def test_block_final_with_text_field(self):
        result = GatewayConnection._transform_chat_event("block_final", {"text": "Complete block."})
        assert result == {"type": "chunk", "content": "Complete block."}

    def test_block_final_with_content_field(self):
        result = GatewayConnection._transform_chat_event("block_final", {"content": "Fallback content"})
        assert result == {"type": "chunk", "content": "Fallback content"}

    def test_block_final_empty_returns_none(self):
        assert GatewayConnection._transform_chat_event("block_final", {}) is None

    def test_turn_completed(self):
        result = GatewayConnection._transform_chat_event("turn_completed", {})
        assert result == {"type": "done"}

    def test_turn_failed_with_error_dict(self):
        result = GatewayConnection._transform_chat_event("turn_failed", {"error": {"message": "Model rate limited"}})
        assert result == {"type": "error", "message": "Model rate limited"}

    def test_turn_failed_with_error_dict_no_message(self):
        result = GatewayConnection._transform_chat_event("turn_failed", {"error": {"code": 500}})
        assert result == {"type": "error", "message": "Agent run failed"}

    def test_turn_failed_with_string_error(self):
        result = GatewayConnection._transform_chat_event("turn_failed", {"error": "Something broke"})
        assert result == {"type": "error", "message": "Something broke"}

    def test_turn_failed_no_error(self):
        result = GatewayConnection._transform_chat_event("turn_failed", {})
        assert result == {"type": "error", "message": "Agent run failed"}

    def test_turn_cancelled(self):
        result = GatewayConnection._transform_chat_event("turn_cancelled", {})
        assert result == {"type": "error", "message": "Agent run was cancelled"}

    def test_turn_started_returns_heartbeat(self):
        result = GatewayConnection._transform_chat_event("turn_started", {})
        assert result == {"type": "heartbeat"}

    def test_tool_started_returns_heartbeat(self):
        result = GatewayConnection._transform_chat_event("tool_started", {"tool": "brave_search"})
        assert result == {"type": "heartbeat"}

    def test_tool_finished_returns_none(self):
        assert GatewayConnection._transform_chat_event("tool_finished", {}) is None

    def test_status_returns_none(self):
        assert GatewayConnection._transform_chat_event("status", {"state": "thinking"}) is None

    def test_unknown_event_returns_none(self):
        assert GatewayConnection._transform_chat_event("unknown_event", {}) is None


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
                "event": "text_delta",
                "payload": {"delta": "Hi!"},
            }
        )
        mock_management_api.send_message.assert_called_once_with("conn-1", {"type": "chunk", "content": "Hi!"})

    def test_non_chat_event_forwarded_as_is(self, connection, mock_management_api):
        """Non-chat events should be forwarded raw for SWR revalidation."""
        raw_event = {"type": "event", "event": "health", "payload": {"status": "ok"}}
        connection._handle_message(raw_event)
        mock_management_api.send_message.assert_called_once_with("conn-1", raw_event)

    def test_skipped_chat_event_not_forwarded(self, connection, mock_management_api):
        """Events that transform to None (tool_finished) should not be forwarded."""
        connection._handle_message(
            {
                "type": "event",
                "event": "tool_finished",
                "payload": {},
            }
        )
        mock_management_api.send_message.assert_not_called()

    def test_turn_completed_sends_done(self, connection, mock_management_api):
        """turn_completed should be transformed to {type: done}."""
        connection._handle_message(
            {
                "type": "event",
                "event": "turn_completed",
                "payload": {},
            }
        )
        mock_management_api.send_message.assert_called_once_with("conn-1", {"type": "done"})

    def test_chat_events_sent_to_all_frontend_connections(self, connection, mock_management_api):
        """Chat events should be forwarded to all registered frontend connections."""
        connection._frontend_connections.add("conn-2")
        connection._handle_message(
            {
                "type": "event",
                "event": "text_delta",
                "payload": {"delta": "chunk"},
            }
        )
        assert mock_management_api.send_message.call_count == 2
