"""
Tests for Debug API (routers/debug.py).

TDD: Tests written BEFORE implementation.
"""

import json
import pytest
from unittest.mock import MagicMock, patch


class TestDebugStatus:
    @pytest.mark.asyncio
    @patch("routers.debug.get_container_manager")
    async def test_get_status(self, mock_get_cm, async_client, test_user):
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = 19000
        mock_cm.exec_command.return_value = json.dumps(
            {
                "gateway": {"status": "running", "uptime": "2h 15m"},
                "agents": 3,
                "sessions": 5,
            }
        )
        mock_get_cm.return_value = mock_cm
        response = await async_client.get("/api/v1/debug/status")
        assert response.status_code == 200
        assert "status" in response.json()

    @pytest.mark.asyncio
    @patch("routers.debug.get_container_manager")
    async def test_status_no_container(self, mock_get_cm, async_client, test_user):
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = None
        mock_get_cm.return_value = mock_cm
        response = await async_client.get("/api/v1/debug/status")
        assert response.status_code == 404


class TestDebugHealth:
    @pytest.mark.asyncio
    @patch("routers.debug.get_container_manager")
    async def test_health_check(self, mock_get_cm, async_client, test_user):
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = 19000
        mock_cm.is_healthy.return_value = True
        mock_get_cm.return_value = mock_cm
        response = await async_client.get("/api/v1/debug/health")
        assert response.status_code == 200
        assert response.json()["healthy"] is True


class TestDebugModels:
    @pytest.mark.asyncio
    @patch("routers.debug.get_container_manager")
    async def test_list_models(self, mock_get_cm, async_client, test_user):
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = 19000
        mock_cm.exec_command.return_value = json.dumps(
            [
                {"id": "us.anthropic.claude-sonnet-4-6", "provider": "amazon-bedrock"},
            ]
        )
        mock_get_cm.return_value = mock_cm
        response = await async_client.get("/api/v1/debug/models")
        assert response.status_code == 200
        assert "models" in response.json()


class TestDebugEvents:
    @pytest.mark.asyncio
    @patch("routers.debug.get_container_manager")
    async def test_list_events(self, mock_get_cm, async_client, test_user):
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = 19000
        mock_cm.exec_command.return_value = json.dumps(
            [
                {"type": "agent.chat", "timestamp": "2026-02-27T10:00:00Z"},
            ]
        )
        mock_get_cm.return_value = mock_cm
        response = await async_client.get("/api/v1/debug/events")
        assert response.status_code == 200
        assert "events" in response.json()


class TestDebugAuth:
    @pytest.mark.asyncio
    async def test_debug_requires_auth(self, unauthenticated_async_client):
        response = await unauthenticated_async_client.get("/api/v1/debug/status")
        assert response.status_code in (401, 403)
