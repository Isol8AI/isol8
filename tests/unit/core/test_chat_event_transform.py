# backend/tests/unit/core/test_chat_event_transform.py
"""Unit tests for GatewayConnection._transform_chat_event().

Verifies that OpenClaw native chat events are correctly transformed into
the frontend's chunk/done/error message format.
"""

import pytest

from core.gateway.connection_pool import GatewayConnection


class TestTransformChatEvent:
    """Tests for _transform_chat_event static method (native chat events only)."""

    def test_chat_delta_with_content_blocks(self):
        """Native format: message.content is an array of content blocks with delta field."""
        result = GatewayConnection._transform_chat_event(
            "chat",
            {
                "state": "delta",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Hello world", "delta": " world"}],
                },
            },
        )
        assert result == {"type": "chunk", "content": " world"}

    def test_chat_delta_content_block_text_fallback(self):
        """When delta is missing, fall back to text field in content block."""
        result = GatewayConnection._transform_chat_event(
            "chat",
            {
                "state": "delta",
                "message": {"content": [{"type": "text", "text": "Hello"}]},
            },
        )
        assert result == {"type": "chunk", "content": "Hello"}

    def test_chat_delta_with_string_content(self):
        """Fallback: message.content is a plain string."""
        result = GatewayConnection._transform_chat_event("chat", {"state": "delta", "message": {"content": "Hello"}})
        assert result == {"type": "chunk", "content": "Hello"}

    def test_chat_delta_with_string_message(self):
        result = GatewayConnection._transform_chat_event("chat", {"state": "delta", "message": "Hi there"})
        assert result == {"type": "chunk", "content": "Hi there"}

    def test_chat_delta_empty_message(self):
        assert GatewayConnection._transform_chat_event("chat", {"state": "delta", "message": {}}) is None
        assert GatewayConnection._transform_chat_event("chat", {"state": "delta"}) is None
        assert GatewayConnection._transform_chat_event("chat", {"state": "delta", "message": {"content": []}}) is None

    def test_chat_final(self):
        result = GatewayConnection._transform_chat_event("chat", {"state": "final"})
        assert result == {"type": "done"}

    def test_chat_error_with_dict(self):
        result = GatewayConnection._transform_chat_event(
            "chat", {"state": "error", "error": {"message": "Rate limited"}}
        )
        assert result == {"type": "error", "message": "Rate limited"}

    def test_chat_error_with_string(self):
        result = GatewayConnection._transform_chat_event("chat", {"state": "error", "error": "Something broke"})
        assert result == {"type": "error", "message": "Something broke"}

    def test_chat_aborted(self):
        result = GatewayConnection._transform_chat_event("chat", {"state": "aborted"})
        assert result == {"type": "error", "message": "Agent run was cancelled"}

    def test_chat_unknown_state(self):
        assert GatewayConnection._transform_chat_event("chat", {"state": "unknown"}) is None

    def test_non_chat_event_returns_none(self):
        assert GatewayConnection._transform_chat_event("text_delta", {"delta": "Hi"}) is None
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
                "event": "chat",
                "payload": {"state": "delta", "message": {"content": [{"type": "text", "delta": "Hi!"}]}},
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
