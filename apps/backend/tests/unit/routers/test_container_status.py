"""Tests for container endpoints: GET /status and POST /gateway/restart."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from routers.container import _resolve_cold_start_phase


class TestColdStartPhaseResolver:
    """Pure unit tests for the (DDB status, pool state) -> phase mapping.

    Drives the frontend stepper. The "starting" phase is the most-visible
    one for users today since it covers the 5+min sidecars.channels wedge.
    """

    @staticmethod
    def _pool(connected: bool):
        return SimpleNamespace(is_user_connected=lambda _uid: connected)

    @pytest.mark.parametrize("status", ["provisioning", "stopped", "error", None, ""])
    def test_anything_not_running_is_provisioning(self, status):
        container = {"status": status} if status is not None else {}
        assert _resolve_cold_start_phase(container, self._pool(False), "u_1") == "provisioning"

    def test_running_without_gateway_handshake_is_starting(self):
        # Covers the gap that takes the longest in practice today —
        # ECS task is up but openclaw is still in plugins.bootstrap or
        # the sidecars.channels wedge.
        container = {"status": "running"}
        assert _resolve_cold_start_phase(container, self._pool(False), "u_1") == "starting"

    def test_running_with_gateway_handshake_is_ready(self):
        container = {"status": "running"}
        assert _resolve_cold_start_phase(container, self._pool(True), "u_1") == "ready"

    def test_none_container_is_provisioning(self):
        # Defensive: status route may briefly hit this if the DDB row is
        # being written concurrently with a poll. Don't crash.
        assert _resolve_cold_start_phase(None, self._pool(False), "u_1") == "provisioning"


class TestContainerStatusPhaseField:
    """Verify the /status response actually carries the phase."""

    @pytest.mark.asyncio
    @patch("routers.container.get_gateway_pool")
    @patch("routers.container.get_ecs_manager")
    async def test_phase_starting_when_running_but_no_pool(self, mock_get_ecs, mock_get_pool, async_client):
        mock_ecs = AsyncMock()
        mock_get_ecs.return_value = mock_ecs
        mock_ecs.resolve_running_container = AsyncMock(
            return_value=(
                {
                    "service_name": "openclaw-abc",
                    "status": "running",
                    "created_at": "2026-01-15T12:00:00+00:00",
                    "updated_at": "2026-01-15T12:00:00+00:00",
                },
                "10.0.1.5",
            )
        )
        mock_get_pool.return_value = SimpleNamespace(is_user_connected=lambda _u: False)

        response = await async_client.get("/api/v1/container/status")
        assert response.status_code == 200
        assert response.json()["phase"] == "starting"

    @pytest.mark.asyncio
    @patch("routers.container.get_gateway_pool")
    @patch("routers.container.get_ecs_manager")
    async def test_phase_ready_when_pool_connected(self, mock_get_ecs, mock_get_pool, async_client):
        mock_ecs = AsyncMock()
        mock_get_ecs.return_value = mock_ecs
        mock_ecs.resolve_running_container = AsyncMock(
            return_value=(
                {
                    "service_name": "openclaw-abc",
                    "status": "running",
                    "created_at": "2026-01-15T12:00:00+00:00",
                    "updated_at": "2026-01-15T12:00:00+00:00",
                },
                "10.0.1.5",
            )
        )
        mock_get_pool.return_value = SimpleNamespace(is_user_connected=lambda _u: True)

        response = await async_client.get("/api/v1/container/status")
        assert response.status_code == 200
        assert response.json()["phase"] == "ready"


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
    async def test_returns_last_error_fields(self, mock_get_ecs, async_client):
        """Should include last_error and last_error_at when present on the container."""
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
                    "last_error": "OutOfMemoryError",
                    "last_error_at": "2026-01-15T13:00:00+00:00",
                },
                "10.0.1.5",
            )
        )

        response = await async_client.get("/api/v1/container/status")
        assert response.status_code == 200
        data = response.json()
        assert data["last_error"] == "OutOfMemoryError"
        assert data["last_error_at"] == "2026-01-15T13:00:00+00:00"

    @pytest.mark.asyncio
    @patch("routers.container.get_ecs_manager")
    async def test_returns_null_last_error_when_absent(self, mock_get_ecs, async_client):
        """Should return null for last_error and last_error_at when not set on the container."""
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
        assert data["last_error"] is None
        assert data["last_error_at"] is None

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
