"""
Tests for Debug API (routers/debug.py).

Only provision/remove endpoints remain after Docker exec cleanup.
"""

import pytest
from unittest.mock import MagicMock, patch


class TestProvisionContainer:
    @pytest.mark.asyncio
    @patch("routers.debug.get_container_manager")
    async def test_provision_new(self, mock_get_cm, async_client, test_user):
        mock_cm = MagicMock()
        mock_cm.available = True
        mock_cm.get_container_port.return_value = None
        mock_cm.provision_container.return_value = MagicMock(port=19000, container_id="abc123")
        mock_get_cm.return_value = mock_cm
        response = await async_client.post("/api/v1/debug/provision")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "provisioned"
        assert data["port"] == 19000

    @pytest.mark.asyncio
    @patch("routers.debug.get_container_manager")
    async def test_provision_already_running(self, mock_get_cm, async_client, test_user):
        mock_cm = MagicMock()
        mock_cm.available = True
        mock_cm.get_container_port.return_value = 19000
        mock_get_cm.return_value = mock_cm
        response = await async_client.post("/api/v1/debug/provision")
        assert response.status_code == 200
        assert response.json()["status"] == "already_running"

    @pytest.mark.asyncio
    @patch("routers.debug.settings")
    async def test_provision_blocked_in_prod(self, mock_settings, async_client, test_user):
        mock_settings.ENVIRONMENT = "prod"
        response = await async_client.post("/api/v1/debug/provision")
        assert response.status_code == 403

    @pytest.mark.asyncio
    @patch("routers.debug.get_container_manager")
    async def test_provision_docker_unavailable(self, mock_get_cm, async_client, test_user):
        mock_cm = MagicMock()
        mock_cm.available = False
        mock_get_cm.return_value = mock_cm
        response = await async_client.post("/api/v1/debug/provision")
        assert response.status_code == 503


class TestRemoveContainer:
    @pytest.mark.asyncio
    @patch("routers.debug.get_container_manager")
    async def test_remove_success(self, mock_get_cm, async_client, test_user):
        mock_cm = MagicMock()
        mock_cm.remove_container.return_value = True
        mock_get_cm.return_value = mock_cm
        response = await async_client.delete("/api/v1/debug/provision")
        assert response.status_code == 200
        assert response.json()["status"] == "removed"

    @pytest.mark.asyncio
    @patch("routers.debug.get_container_manager")
    async def test_remove_not_found(self, mock_get_cm, async_client, test_user):
        mock_cm = MagicMock()
        mock_cm.remove_container.return_value = False
        mock_get_cm.return_value = mock_cm
        response = await async_client.delete("/api/v1/debug/provision")
        assert response.status_code == 404

    @pytest.mark.asyncio
    @patch("routers.debug.settings")
    async def test_remove_blocked_in_prod(self, mock_settings, async_client, test_user):
        mock_settings.ENVIRONMENT = "prod"
        response = await async_client.delete("/api/v1/debug/provision")
        assert response.status_code == 403


class TestDebugAuth:
    @pytest.mark.asyncio
    async def test_debug_requires_auth(self, unauthenticated_async_client):
        response = await unauthenticated_async_client.post("/api/v1/debug/provision")
        assert response.status_code in (401, 403)
