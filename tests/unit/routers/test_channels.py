"""
Tests for Channels API (routers/channels.py).

TDD: Tests written BEFORE implementation.
"""

import json
import pytest
from unittest.mock import MagicMock, patch


class TestListChannels:
    @pytest.mark.asyncio
    @patch("routers.channels.get_container_manager")
    async def test_list_channels(self, mock_get_cm, async_client, test_user):
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = 19000
        mock_cm.exec_command.return_value = json.dumps(
            [
                {"name": "whatsapp", "enabled": True, "status": "connected"},
                {"name": "telegram", "enabled": False, "status": "disconnected"},
                {"name": "discord", "enabled": False, "status": "not_configured"},
            ]
        )
        mock_get_cm.return_value = mock_cm
        response = await async_client.get("/api/v1/channels")
        assert response.status_code == 200
        data = response.json()
        assert "channels" in data
        assert len(data["channels"]) == 3

    @pytest.mark.asyncio
    @patch("routers.channels.get_container_manager")
    async def test_channels_no_container(self, mock_get_cm, async_client, test_user):
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = None
        mock_get_cm.return_value = mock_cm
        response = await async_client.get("/api/v1/channels")
        assert response.status_code == 404


class TestConfigureChannel:
    @pytest.mark.asyncio
    @patch("routers.channels.get_container_manager")
    async def test_configure_channel(self, mock_get_cm, async_client, test_user):
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = 19000
        mock_cm.exec_command.return_value = ""
        mock_get_cm.return_value = mock_cm
        response = await async_client.put(
            "/api/v1/channels/telegram",
            json={
                "config": {"botToken": "123:ABC"},
            },
        )
        assert response.status_code == 200


class TestToggleChannel:
    @pytest.mark.asyncio
    @patch("routers.channels.get_container_manager")
    async def test_enable_channel(self, mock_get_cm, async_client, test_user):
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = 19000
        mock_cm.exec_command.return_value = ""
        mock_get_cm.return_value = mock_cm
        response = await async_client.post("/api/v1/channels/telegram/enable")
        assert response.status_code == 200

    @pytest.mark.asyncio
    @patch("routers.channels.get_container_manager")
    async def test_disable_channel(self, mock_get_cm, async_client, test_user):
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = 19000
        mock_cm.exec_command.return_value = ""
        mock_get_cm.return_value = mock_cm
        response = await async_client.post("/api/v1/channels/telegram/disable")
        assert response.status_code == 200


class TestChannelsAuth:
    @pytest.mark.asyncio
    async def test_channels_requires_auth(self, unauthenticated_async_client):
        response = await unauthenticated_async_client.get("/api/v1/channels")
        assert response.status_code in (401, 403)
