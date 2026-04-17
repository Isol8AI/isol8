"""
Unit tests for WebSocket HTTP routes (API Gateway integration).

Tests the HTTP routes that handle API Gateway WebSocket events:
- POST /ws/connect - Handle $connect event
- POST /ws/disconnect - Handle $disconnect event
- POST /ws/message - Handle $default (message) events

These tests use httpx AsyncClient with ASGITransport for testing HTTP endpoints.
Services are mocked to isolate route logic.
"""

import asyncio

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


@pytest.fixture(autouse=True)
def mock_gateway_pool():
    """Mock gateway connection pool (autouse since it's called in connect/disconnect)."""
    with patch("routers.websocket_chat.get_gateway_pool") as mock_getter:
        mock_pool = MagicMock()
        mock_getter.return_value = mock_pool
        yield mock_pool


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
    async def test_connect_records_activity_for_personal_owner(self, test_app, mock_connection_service, mock_gateway_pool):
        """Connect must call record_activity(owner_id) so the scale-to-zero
        idle reaper sees a fresh last_active_at immediately after login.

        Without this, there is a 0-65 second window before the frontend's
        first user_active heartbeat lands where the reaper can fire on a
        stale timestamp from a prior session and stop the user's container
        right after they connect.

        For personal users, owner_id == user_id (no org).
        """
        mock_gateway_pool.record_activity = MagicMock(return_value=asyncio.sleep(0))

        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
            response = await client.post(
                "/ws/connect",
                headers={
                    "x-connection-id": "test-conn-123",
                    "x-user-id": "test-user-456",
                },
            )
        # Yield once so the asyncio.create_task fires inside the event loop.
        await asyncio.sleep(0)

        assert response.status_code == 200
        mock_gateway_pool.record_activity.assert_called_once_with("test-user-456")

    @pytest.mark.asyncio
    async def test_connect_records_activity_for_org_owner(self, test_app, mock_connection_service, mock_gateway_pool):
        """Same activity recording for org-context connects, but routed by
        org_id (which is the owner_id) rather than user_id.
        """
        mock_gateway_pool.record_activity = MagicMock(return_value=asyncio.sleep(0))

        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
            response = await client.post(
                "/ws/connect",
                headers={
                    "x-connection-id": "test-conn-123",
                    "x-user-id": "test-user-456",
                    "x-org-id": "test-org-789",
                },
            )
        await asyncio.sleep(0)

        assert response.status_code == 200
        mock_gateway_pool.record_activity.assert_called_once_with("test-org-789")

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


class TestReqMessageRouting:
    """Tests for type=req RPC proxy messages."""

    @pytest.mark.asyncio
    async def test_req_message_accepted(self, test_app, mock_connection_service, mock_management_api):
        """Valid req message should be accepted and return 200."""
        mock_connection_service.get_connection.return_value = {
            "user_id": "test-user",
            "org_id": None,
        }

        with patch("routers.websocket_chat._process_rpc_background") as mock_bg:
            async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
                response = await client.post(
                    "/ws/message",
                    headers={"x-connection-id": "conn-123"},
                    json={
                        "type": "req",
                        "id": "req-uuid-1",
                        "method": "health",
                        "params": {},
                    },
                )

        assert response.status_code == 200
        mock_management_api.send_message.assert_not_called()
        mock_bg.assert_called_once()

    @pytest.mark.asyncio
    async def test_req_background_task_receives_correct_args(
        self, test_app, mock_connection_service, mock_management_api
    ):
        """Background task should receive connection_id, user_id, req_id, method, params."""
        mock_connection_service.get_connection.return_value = {
            "user_id": "test-user",
            "org_id": None,
        }

        with patch("routers.websocket_chat._process_rpc_background") as mock_bg:
            async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
                await client.post(
                    "/ws/message",
                    headers={"x-connection-id": "conn-123"},
                    json={
                        "type": "req",
                        "id": "req-uuid-1",
                        "method": "agents.list",
                        "params": {"filter": "active"},
                    },
                )

        mock_bg.assert_called_once_with(
            connection_id="conn-123",
            user_id="test-user",
            owner_id="test-user",
            req_id="req-uuid-1",
            method="agents.list",
            params={"filter": "active"},
        )

    @pytest.mark.asyncio
    async def test_req_missing_id_sends_error(self, test_app, mock_connection_service, mock_management_api):
        """req without id should send error res back."""
        mock_connection_service.get_connection.return_value = {
            "user_id": "test-user",
            "org_id": None,
        }

        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
            response = await client.post(
                "/ws/message",
                headers={"x-connection-id": "conn-123"},
                json={"type": "req", "method": "health"},
            )

        assert response.status_code == 200
        mock_management_api.send_message.assert_called_once()
        sent_msg = mock_management_api.send_message.call_args[0][1]
        assert sent_msg["type"] == "res"
        assert sent_msg["ok"] is False

    @pytest.mark.asyncio
    async def test_req_missing_method_sends_error(self, test_app, mock_connection_service, mock_management_api):
        """req without method should send error res back."""
        mock_connection_service.get_connection.return_value = {
            "user_id": "test-user",
            "org_id": None,
        }

        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
            response = await client.post(
                "/ws/message",
                headers={"x-connection-id": "conn-123"},
                json={"type": "req", "id": "req-uuid-2"},
            )

        assert response.status_code == 200
        sent_msg = mock_management_api.send_message.call_args[0][1]
        assert sent_msg["type"] == "res"
        assert sent_msg["id"] == "req-uuid-2"
        assert sent_msg["ok"] is False


class TestActivityTracking:
    """Tests for activity tracking dispatch (scale-to-zero idle detection)."""

    @pytest.mark.asyncio
    async def test_user_active_dispatch_calls_record_activity(
        self, test_app, mock_connection_service, mock_management_api, mock_gateway_pool
    ):
        """user_active message should call pool.record_activity(owner_id) exactly once and return 200."""
        from unittest.mock import AsyncMock

        mock_connection_service.get_connection.return_value = {
            "user_id": "test-user",
            "org_id": None,
        }
        mock_gateway_pool.record_activity = AsyncMock()

        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
            response = await client.post(
                "/ws/message",
                headers={"x-connection-id": "conn-abc"},
                json={"type": "user_active"},
            )

        assert response.status_code == 200
        # record_activity is scheduled fire-and-forget via asyncio.create_task
        # so the handler can return before DDB latency. Drain pending tasks.
        await asyncio.sleep(0)
        mock_gateway_pool.record_activity.assert_awaited_once_with("test-user")
        mock_management_api.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_user_active_dispatch_uses_org_owner_id(
        self, test_app, mock_connection_service, mock_management_api, mock_gateway_pool
    ):
        """user_active should record activity under org_id when connection has one."""
        from unittest.mock import AsyncMock

        mock_connection_service.get_connection.return_value = {
            "user_id": "test-user",
            "org_id": "test-org-789",
        }
        mock_gateway_pool.record_activity = AsyncMock()

        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
            response = await client.post(
                "/ws/message",
                headers={"x-connection-id": "conn-abc"},
                json={"type": "user_active"},
            )

        assert response.status_code == 200
        await asyncio.sleep(0)  # drain the fire-and-forget task
        mock_gateway_pool.record_activity.assert_awaited_once_with("test-org-789")

    @pytest.mark.asyncio
    async def test_agent_chat_dispatch_calls_record_activity(
        self, test_app, mock_connection_service, mock_management_api, mock_gateway_pool
    ):
        """agent_chat should route through record_activity (not touch_activity)."""
        from unittest.mock import AsyncMock

        mock_connection_service.get_connection.return_value = {
            "user_id": "test-user",
            "org_id": None,
        }
        mock_gateway_pool.record_activity = AsyncMock()
        # Guard: if agent_chat still calls touch_activity, fail loudly (None is not callable).
        mock_gateway_pool.touch_activity = None

        with (
            patch(
                "core.services.usage_service.check_budget",
                new_callable=AsyncMock,
                return_value={"allowed": True},
            ),
            patch("routers.websocket_chat._process_agent_chat_background"),
        ):
            async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
                response = await client.post(
                    "/ws/message",
                    headers={"x-connection-id": "conn-abc"},
                    json={"type": "agent_chat", "agent_id": "a1", "message": "hello"},
                )

        assert response.status_code == 200
        await asyncio.sleep(0)  # drain the fire-and-forget task
        mock_gateway_pool.record_activity.assert_awaited_once_with("test-user")
