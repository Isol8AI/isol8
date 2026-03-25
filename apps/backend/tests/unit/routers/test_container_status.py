"""Tests for container endpoints: GET /status and POST /gateway/restart."""

from unittest.mock import AsyncMock, patch

import pytest


class TestContainerStatus:
    """Test GET /api/v1/container/status."""

    @pytest.mark.asyncio
    @patch("routers.container.get_ecs_manager")
    async def test_returns_container_status(self, mock_get_ecs, async_client):
        """Should return container metadata for authenticated user."""
        mock_ecs = AsyncMock()
        mock_get_ecs.return_value = mock_ecs
        mock_ecs.resolve_running_container = AsyncMock(
            return_value=(
                {
                    "owner_id": "user_test_123",
                    "service_name": "openclaw-abc123",
                    "gateway_token": "secret-token-value",
                    "status": "running",
                    "substatus": None,
                    "task_arn": "arn:aws:ecs:us-east-1:123456789:task/test-task",
                    "access_point_id": "fsap-test123",
                    "created_at": "2026-01-15T12:00:00+00:00",
                    "updated_at": "2026-01-15T14:00:00+00:00",
                },
                "10.0.1.5",
            )
        )

        response = await async_client.get("/api/v1/container/status")
        assert response.status_code == 200
        data = response.json()
        assert data["service_name"] == "openclaw-abc123"
        assert data["status"] == "running"
        assert data["substatus"] is None
        assert data["region"] == "us-east-1"
        assert "created_at" in data
        assert "updated_at" in data

    @pytest.mark.asyncio
    @patch("routers.container.get_ecs_manager")
    async def test_excludes_sensitive_fields(self, mock_get_ecs, async_client):
        """Should never expose gateway_token, task_arn, or access_point_id."""
        mock_ecs = AsyncMock()
        mock_get_ecs.return_value = mock_ecs
        mock_ecs.resolve_running_container = AsyncMock(
            return_value=(
                {
                    "owner_id": "user_test_123",
                    "service_name": "openclaw-abc123",
                    "gateway_token": "secret-token-value",
                    "status": "running",
                    "substatus": None,
                    "task_arn": "arn:aws:ecs:us-east-1:123456789:task/test-task",
                    "access_point_id": "fsap-test123",
                    "created_at": "2026-01-15T12:00:00+00:00",
                    "updated_at": "2026-01-15T14:00:00+00:00",
                },
                "10.0.1.5",
            )
        )

        response = await async_client.get("/api/v1/container/status")
        assert response.status_code == 200
        data = response.json()
        assert "gateway_token" not in data
        assert "task_arn" not in data
        assert "access_point_id" not in data
        assert "task_definition_arn" not in data

    @pytest.mark.asyncio
    @patch("routers.container.get_ecs_manager")
    async def test_returns_404_without_container(self, mock_get_ecs, async_client):
        """Should return 404 when user has no container."""
        mock_ecs = AsyncMock()
        mock_get_ecs.return_value = mock_ecs
        mock_ecs.resolve_running_container = AsyncMock(return_value=(None, None))
        mock_ecs.get_service_status = AsyncMock(return_value=None)
        response = await async_client.get("/api/v1/container/status")
        assert response.status_code == 404


class TestGatewayRestart:
    """Test POST /api/v1/container/gateway/restart."""

    @pytest.fixture
    def mock_ecs_manager(self):
        with patch("routers.container_rpc.get_ecs_manager") as mock_getter:
            manager = AsyncMock()
            mock_getter.return_value = manager
            yield manager

    @pytest.fixture
    def mock_call_gateway_rpc(self):
        with patch("routers.container_rpc._call_gateway_rpc", new_callable=AsyncMock) as mock_rpc:
            mock_rpc.return_value = {}
            yield mock_rpc

    @pytest.fixture
    def running_container(self, mock_ecs_manager):
        """Set up ECS manager to return a running container with IP."""
        container = {
            "gateway_token": "test-gw-token",
            "owner_id": "user_test_123",
            "service_name": "openclaw-test",
            "status": "running",
        }
        mock_ecs_manager.resolve_running_container = AsyncMock(return_value=(container, "10.0.1.5"))
        return container

    @pytest.mark.asyncio
    async def test_gateway_restart_success(
        self, async_client, mock_ecs_manager, mock_call_gateway_rpc, running_container
    ):
        """Happy path: should return ok=true and call config.apply RPC."""
        response = await async_client.post("/api/v1/container/gateway/restart")
        assert response.status_code == 200
        assert response.json() == {"ok": True}
        mock_call_gateway_rpc.assert_called_once_with(
            ip="10.0.1.5",
            token="test-gw-token",
            method="config.apply",
            params={},
        )

    @pytest.mark.asyncio
    async def test_gateway_restart_no_container(self, async_client, mock_ecs_manager, mock_call_gateway_rpc):
        """Should return 404 when no container is found."""
        mock_ecs_manager.resolve_running_container = AsyncMock(return_value=(None, None))
        response = await async_client.post("/api/v1/container/gateway/restart")
        assert response.status_code == 404
        assert "No running container" in response.json()["detail"]
        mock_call_gateway_rpc.assert_not_called()

    @pytest.mark.asyncio
    async def test_gateway_restart_gateway_unreachable(
        self, async_client, mock_ecs_manager, mock_call_gateway_rpc, running_container
    ):
        """Should return 502 when gateway refuses connection."""
        mock_call_gateway_rpc.side_effect = ConnectionRefusedError()
        response = await async_client.post("/api/v1/container/gateway/restart")
        assert response.status_code == 502
        assert "Gateway is not responding" in response.json()["detail"]
