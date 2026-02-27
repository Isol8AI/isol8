"""
Unit tests for WebSocket agent_chat message type routing and validation.

Tests the agent_chat message type in POST /ws/message:
- Routing: agent_chat messages are accepted and background task is queued
- Validation: missing fields send errors via Management API

Uses the same pattern as test_websocket_chat.py:
- httpx AsyncClient with ASGITransport for HTTP endpoint testing
- Mocked ConnectionService and ManagementApiClient to isolate route logic
"""

import pytest
from unittest.mock import MagicMock, patch
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from routers.websocket_chat import router


@pytest.fixture
def test_app():
    """Create a test FastAPI app with the websocket router."""
    app = FastAPI()
    app.include_router(router, prefix="/ws")
    return app


@pytest.fixture
def mock_connection_service():
    """Mock ConnectionService for testing."""
    with patch("routers.websocket_chat.get_connection_service") as mock_getter:
        mock_service = MagicMock()
        mock_getter.return_value = mock_service
        yield mock_service


@pytest.fixture
def mock_management_api():
    """Mock ManagementApiClient for testing."""
    with patch("routers.websocket_chat.get_management_api_client") as mock_getter:
        mock_client = MagicMock()
        mock_client.send_message = MagicMock(return_value=True)
        mock_getter.return_value = mock_client
        yield mock_client


@pytest.fixture
def valid_agent_chat_message():
    """Create a valid agent_chat message payload (plaintext)."""
    return {
        "type": "agent_chat",
        "agent_name": "my-agent",
        "message": "Hello, agent!",
    }


@pytest.fixture
def connected_user(mock_connection_service):
    """Set up mock connection service to return a connected user."""
    mock_connection_service.get_connection.return_value = {
        "user_id": "test-user-456",
        "org_id": None,
    }
    return "test-user-456"


class TestAgentChatMessageRouting:
    """Tests that the ws_message endpoint correctly routes agent_chat messages."""

    @pytest.mark.asyncio
    async def test_agent_chat_message_accepted(
        self, test_app, mock_connection_service, mock_management_api, valid_agent_chat_message, connected_user
    ):
        """Send valid agent_chat message, verify 200 response.

        A valid agent_chat message should be accepted and return 200.
        The background task is queued but not awaited in the HTTP handler.
        """
        with patch("routers.websocket_chat._process_agent_chat_background") as mock_bg:
            async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
                response = await client.post(
                    "/ws/message",
                    headers={"x-connection-id": "test-conn-123"},
                    json=valid_agent_chat_message,
                )

        assert response.status_code == 200
        # No error should be sent via Management API for a valid message
        mock_management_api.send_message.assert_not_called()
        # Background task should have been queued (called by BackgroundTasks)
        mock_bg.assert_called_once()

    @pytest.mark.asyncio
    async def test_agent_chat_missing_agent_name_sends_error(
        self, test_app, mock_connection_service, mock_management_api, connected_user
    ):
        """Missing agent_name field should send error via Management API."""
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
            response = await client.post(
                "/ws/message",
                headers={"x-connection-id": "test-conn-123"},
                json={
                    "type": "agent_chat",
                    "message": "Hello!",
                    # agent_name missing
                },
            )

        assert response.status_code == 200
        mock_management_api.send_message.assert_called_once()
        call_args = mock_management_api.send_message.call_args
        assert call_args[0][0] == "test-conn-123"
        assert call_args[0][1]["type"] == "error"

    @pytest.mark.asyncio
    async def test_agent_chat_missing_message_sends_error(
        self, test_app, mock_connection_service, mock_management_api, connected_user
    ):
        """Missing message field should send error via Management API."""
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
            response = await client.post(
                "/ws/message",
                headers={"x-connection-id": "test-conn-123"},
                json={
                    "type": "agent_chat",
                    "agent_name": "my-agent",
                    # message missing
                },
            )

        assert response.status_code == 200
        mock_management_api.send_message.assert_called_once()
        call_args = mock_management_api.send_message.call_args
        assert call_args[0][0] == "test-conn-123"
        assert call_args[0][1]["type"] == "error"

    @pytest.mark.asyncio
    async def test_agent_chat_empty_fields_sends_error(
        self, test_app, mock_connection_service, mock_management_api, connected_user
    ):
        """Empty agent_name and message should send error via Management API."""
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
            response = await client.post(
                "/ws/message",
                headers={"x-connection-id": "test-conn-123"},
                json={
                    "type": "agent_chat",
                    "agent_name": "",
                    "message": "",
                },
            )

        assert response.status_code == 200
        mock_management_api.send_message.assert_called_once()
        call_args = mock_management_api.send_message.call_args
        assert call_args[0][1]["type"] == "error"


class TestAgentChatBackgroundTask:
    """Tests for the _process_agent_chat_background function arguments."""

    @pytest.mark.asyncio
    async def test_background_task_receives_correct_args(
        self, test_app, mock_connection_service, mock_management_api, connected_user
    ):
        """Background task should receive connection_id, user_id, agent_name, message."""
        with patch("routers.websocket_chat._process_agent_chat_background") as mock_bg:
            async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
                await client.post(
                    "/ws/message",
                    headers={"x-connection-id": "test-conn-123"},
                    json={
                        "type": "agent_chat",
                        "agent_name": "luna",
                        "message": "Tell me a story",
                    },
                )

        mock_bg.assert_called_once_with(
            connection_id="test-conn-123",
            user_id="test-user-456",
            agent_name="luna",
            message="Tell me a story",
        )
