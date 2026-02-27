"""
Unit tests for WebSocket HTTP routes (API Gateway integration).

Tests the HTTP routes that handle API Gateway WebSocket events:
- POST /ws/connect - Handle $connect event
- POST /ws/disconnect - Handle $disconnect event
- POST /ws/message - Handle $default (message) events

These tests use httpx AsyncClient with ASGITransport for testing HTTP endpoints.
Services are mocked to isolate route logic.
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
def mock_session_factory():
    """Mock database session factory."""
    with patch("routers.websocket_chat.get_session_factory") as mock_getter:
        mock_factory = MagicMock()
        mock_getter.return_value = mock_factory
        yield mock_factory


class TestConnectEndpoint:
    """Tests for POST /ws/connect endpoint."""

    @pytest.mark.asyncio
    async def test_connect_stores_connection(self, test_app, mock_connection_service):
        """Connect should store connection in DynamoDB."""
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
            response = await client.post(
                "/ws/connect",
                headers={
                    "x-connection-id": "test-conn-123",
                    "x-user-id": "test-user-456",
                },
            )

        assert response.status_code == 200
        mock_connection_service.store_connection.assert_called_once_with(
            connection_id="test-conn-123",
            user_id="test-user-456",
            org_id=None,
        )

    @pytest.mark.asyncio
    async def test_connect_stores_connection_with_org_id(self, test_app, mock_connection_service):
        """Connect should store org_id when provided."""
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
            response = await client.post(
                "/ws/connect",
                headers={
                    "x-connection-id": "test-conn-123",
                    "x-user-id": "test-user-456",
                    "x-org-id": "test-org-789",
                },
            )

        assert response.status_code == 200
        mock_connection_service.store_connection.assert_called_once_with(
            connection_id="test-conn-123",
            user_id="test-user-456",
            org_id="test-org-789",
        )

    @pytest.mark.asyncio
    async def test_connect_without_connection_id_fails(self, test_app, mock_connection_service):
        """Connect without x-connection-id header should return 400."""
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
            response = await client.post(
                "/ws/connect",
                headers={
                    "x-user-id": "test-user-456",
                },
            )

        assert response.status_code == 400
        assert "connection-id" in response.json()["detail"].lower()
        mock_connection_service.store_connection.assert_not_called()

    @pytest.mark.asyncio
    async def test_connect_without_user_id_fails(self, test_app, mock_connection_service):
        """Connect without x-user-id header should return 401."""
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
            response = await client.post(
                "/ws/connect",
                headers={
                    "x-connection-id": "test-conn-123",
                },
            )

        assert response.status_code == 401
        assert "user-id" in response.json()["detail"].lower()
        mock_connection_service.store_connection.assert_not_called()


class TestDisconnectEndpoint:
    """Tests for POST /ws/disconnect endpoint."""

    @pytest.mark.asyncio
    async def test_disconnect_deletes_connection(self, test_app, mock_connection_service):
        """Disconnect should delete connection from DynamoDB."""
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
            response = await client.post(
                "/ws/disconnect",
                headers={
                    "x-connection-id": "test-conn-123",
                },
            )

        assert response.status_code == 200
        mock_connection_service.delete_connection.assert_called_once_with("test-conn-123")

    @pytest.mark.asyncio
    async def test_disconnect_without_connection_id_returns_200(self, test_app, mock_connection_service):
        """Disconnect without connection-id should still return 200 (best effort)."""
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
            response = await client.post(
                "/ws/disconnect",
                headers={},
            )

        # Best effort cleanup - always returns 200
        assert response.status_code == 200
        mock_connection_service.delete_connection.assert_not_called()

    @pytest.mark.asyncio
    async def test_disconnect_handles_service_error(self, test_app, mock_connection_service):
        """Disconnect should return 200 even if service throws error (best effort)."""
        from core.services.connection_service import ConnectionServiceError

        mock_connection_service.delete_connection.side_effect = ConnectionServiceError("DynamoDB error")

        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
            response = await client.post(
                "/ws/disconnect",
                headers={
                    "x-connection-id": "test-conn-123",
                },
            )

        # Best effort cleanup - always returns 200
        assert response.status_code == 200


class TestMessageEndpoint:
    """Tests for POST /ws/message endpoint."""

    @pytest.mark.asyncio
    async def test_message_looks_up_connection(self, test_app, mock_connection_service, mock_management_api):
        """Message should look up connection to get user context."""
        mock_connection_service.get_connection.return_value = {
            "user_id": "test-user-456",
            "org_id": None,
        }

        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
            response = await client.post(
                "/ws/message",
                headers={
                    "x-connection-id": "test-conn-123",
                },
                json={"type": "ping"},
            )

        assert response.status_code == 200
        mock_connection_service.get_connection.assert_called_once_with("test-conn-123")

    @pytest.mark.asyncio
    async def test_message_handles_ping(self, test_app, mock_connection_service, mock_management_api):
        """Ping message should respond with pong via Management API."""
        mock_connection_service.get_connection.return_value = {
            "user_id": "test-user-456",
            "org_id": None,
        }

        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
            response = await client.post(
                "/ws/message",
                headers={
                    "x-connection-id": "test-conn-123",
                },
                json={"type": "ping"},
            )

        assert response.status_code == 200
        mock_management_api.send_message.assert_called_once_with(
            "test-conn-123",
            {"type": "pong"},
        )

    @pytest.mark.asyncio
    async def test_message_rejects_unknown_connection(self, test_app, mock_connection_service, mock_management_api):
        """Message with unknown connection should return 401."""
        mock_connection_service.get_connection.return_value = None

        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
            response = await client.post(
                "/ws/message",
                headers={
                    "x-connection-id": "unknown-conn",
                },
                json={"type": "ping"},
            )

        assert response.status_code == 401
        assert "unknown connection" in response.json()["detail"].lower()
        mock_management_api.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_message_without_connection_id_fails(self, test_app, mock_connection_service, mock_management_api):
        """Message without x-connection-id should return 400."""
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
            response = await client.post(
                "/ws/message",
                headers={},
                json={"type": "ping"},
            )

        assert response.status_code == 400
        assert "connection-id" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_message_handles_pong_silently(self, test_app, mock_connection_service, mock_management_api):
        """Pong messages should be acknowledged silently (no response sent)."""
        mock_connection_service.get_connection.return_value = {
            "user_id": "test-user-456",
            "org_id": None,
        }

        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
            response = await client.post(
                "/ws/message",
                headers={
                    "x-connection-id": "test-conn-123",
                },
                json={"type": "pong"},
            )

        assert response.status_code == 200
        # Pong is a client ack - no response needed
        mock_management_api.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_message_type_sends_error(self, test_app, mock_connection_service, mock_management_api):
        """Unknown message type should send error via Management API."""
        mock_connection_service.get_connection.return_value = {
            "user_id": "test-user-456",
            "org_id": None,
        }

        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
            response = await client.post(
                "/ws/message",
                headers={
                    "x-connection-id": "test-conn-123",
                },
                json={"type": "invalid_type"},
            )

        assert response.status_code == 200
        mock_management_api.send_message.assert_called_once()
        call_args = mock_management_api.send_message.call_args
        assert call_args[0][0] == "test-conn-123"
        assert call_args[0][1]["type"] == "error"
        assert "unknown message type" in call_args[0][1]["message"].lower()
