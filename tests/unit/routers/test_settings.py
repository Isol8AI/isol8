"""
Tests for Settings API (routers/settings.py).

TDD: Tests written BEFORE implementation.
Tests the user's OpenClaw container settings management.
"""

import json

import pytest
from unittest.mock import MagicMock, patch


class TestGetConfig:
    """Test GET /api/v1/settings/config."""

    @pytest.mark.asyncio
    @patch("routers.settings.get_container_manager")
    async def test_get_config_returns_sanitized_config(self, mock_get_cm, async_client, test_user):
        """Returns the user's openclaw.json with credentials stripped."""
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = 19000
        mock_cm.exec_command.return_value = json.dumps(
            {
                "gateway": {"mode": "local", "auth": {"mode": "none"}},
                "models": {
                    "providers": {
                        "amazon-bedrock": {
                            "baseUrl": "https://bedrock.us-east-1.amazonaws.com",
                            "auth": "aws-sdk",
                        }
                    }
                },
                "tools": {"web": {"search": {"enabled": True, "provider": "brave"}}},
            }
        )
        mock_get_cm.return_value = mock_cm

        response = await async_client.get("/api/v1/settings/config")
        assert response.status_code == 200
        data = response.json()
        assert "gateway" in data["config"]
        assert "tools" in data["config"]

    @pytest.mark.asyncio
    @patch("routers.settings.get_container_manager")
    async def test_get_config_no_container_returns_404(self, mock_get_cm, async_client, test_user):
        """Returns 404 when user has no container (free tier)."""
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = None
        mock_get_cm.return_value = mock_cm

        response = await async_client.get("/api/v1/settings/config")
        assert response.status_code == 404


class TestUpdateConfig:
    """Test PUT /api/v1/settings/config."""

    @pytest.mark.asyncio
    @patch("routers.settings.get_container_manager")
    async def test_update_config_merges_changes(self, mock_get_cm, async_client, test_user):
        """Partial config update is deep-merged with existing config."""
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = 19000
        mock_cm.exec_command.return_value = json.dumps(
            {
                "gateway": {"mode": "local"},
                "tools": {"web": {"search": {"enabled": False}}},
            }
        )
        mock_get_cm.return_value = mock_cm

        response = await async_client.put(
            "/api/v1/settings/config",
            json={"tools": {"web": {"search": {"enabled": True}}}},
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    @patch("routers.settings.get_container_manager")
    async def test_update_config_no_container_returns_404(self, mock_get_cm, async_client, test_user):
        """Returns 404 when user has no container."""
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = None
        mock_get_cm.return_value = mock_cm

        response = await async_client.put(
            "/api/v1/settings/config",
            json={"tools": {"web": {"search": {"enabled": True}}}},
        )
        assert response.status_code == 404


class TestGetModels:
    """Test GET /api/v1/settings/models."""

    @pytest.mark.asyncio
    @patch("routers.settings.get_container_manager")
    async def test_get_models(self, mock_get_cm, async_client, test_user):
        """Returns model/provider configuration."""
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = 19000
        mock_cm.exec_command.return_value = json.dumps(
            {
                "models": {
                    "providers": {
                        "amazon-bedrock": {"auth": "aws-sdk"},
                    },
                    "bedrockDiscovery": {"enabled": False},
                },
            }
        )
        mock_get_cm.return_value = mock_cm

        response = await async_client.get("/api/v1/settings/models")
        assert response.status_code == 200
        data = response.json()
        assert "providers" in data


class TestGetTools:
    """Test GET /api/v1/settings/tools."""

    @pytest.mark.asyncio
    @patch("routers.settings.get_container_manager")
    async def test_get_tools(self, mock_get_cm, async_client, test_user):
        """Returns tool configuration."""
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = 19000
        mock_cm.exec_command.return_value = json.dumps(
            {
                "tools": {
                    "web": {"search": {"enabled": True, "provider": "brave"}},
                },
                "browser": {"enabled": False},
            }
        )
        mock_get_cm.return_value = mock_cm

        response = await async_client.get("/api/v1/settings/tools")
        assert response.status_code == 200
        data = response.json()
        assert "tools" in data


class TestListMemory:
    """Test GET /api/v1/settings/memory."""

    @pytest.mark.asyncio
    @patch("routers.settings.get_container_manager")
    async def test_list_memory(self, mock_get_cm, async_client, test_user):
        """Returns memory entries from container."""
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = 19000
        mock_cm.exec_command.return_value = json.dumps(
            [
                {"id": "mem-1", "content": "User likes hiking", "created_at": "2026-01-15"},
                {"id": "mem-2", "content": "User is a developer", "created_at": "2026-01-16"},
            ]
        )
        mock_get_cm.return_value = mock_cm

        response = await async_client.get("/api/v1/settings/memory")
        assert response.status_code == 200
        data = response.json()
        assert "entries" in data
        assert len(data["entries"]) == 2

    @pytest.mark.asyncio
    @patch("routers.settings.get_container_manager")
    async def test_list_memory_no_container(self, mock_get_cm, async_client, test_user):
        """Returns 404 when user has no container."""
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = None
        mock_get_cm.return_value = mock_cm

        response = await async_client.get("/api/v1/settings/memory")
        assert response.status_code == 404


class TestDeleteMemory:
    """Test DELETE /api/v1/settings/memory/{memory_id}."""

    @pytest.mark.asyncio
    @patch("routers.settings.get_container_manager")
    async def test_delete_memory_entry(self, mock_get_cm, async_client, test_user):
        """Deletes a memory entry inside the container."""
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = 19000
        mock_cm.exec_command.return_value = ""
        mock_get_cm.return_value = mock_cm

        response = await async_client.delete("/api/v1/settings/memory/mem-123")
        assert response.status_code == 204


class TestListSessions:
    """Test GET /api/v1/settings/sessions."""

    @pytest.mark.asyncio
    @patch("routers.settings.get_container_manager")
    async def test_list_sessions(self, mock_get_cm, async_client, test_user):
        """Returns session list from container."""
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = 19000
        mock_cm.exec_command.return_value = json.dumps(
            [
                {"id": "sess-1", "agent": "luna", "created_at": "2026-01-15"},
            ]
        )
        mock_get_cm.return_value = mock_cm

        response = await async_client.get("/api/v1/settings/sessions")
        assert response.status_code == 200
        data = response.json()
        assert "sessions" in data

    @pytest.mark.asyncio
    @patch("routers.settings.get_container_manager")
    async def test_list_sessions_no_container(self, mock_get_cm, async_client, test_user):
        """Returns 404 when user has no container."""
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = None
        mock_get_cm.return_value = mock_cm

        response = await async_client.get("/api/v1/settings/sessions")
        assert response.status_code == 404


class TestDeleteSession:
    """Test DELETE /api/v1/settings/sessions/{session_id}."""

    @pytest.mark.asyncio
    @patch("routers.settings.get_container_manager")
    async def test_delete_session(self, mock_get_cm, async_client, test_user):
        """Deletes a session inside the container."""
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = 19000
        mock_cm.exec_command.return_value = ""
        mock_get_cm.return_value = mock_cm

        response = await async_client.delete("/api/v1/settings/sessions/sess-123")
        assert response.status_code == 204


class TestSettingsAuth:
    """Test that settings endpoints require authentication."""

    @pytest.mark.asyncio
    async def test_config_requires_auth(self, unauthenticated_async_client):
        response = await unauthenticated_async_client.get("/api/v1/settings/config")
        assert response.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_memory_requires_auth(self, unauthenticated_async_client):
        response = await unauthenticated_async_client.get("/api/v1/settings/memory")
        assert response.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_sessions_requires_auth(self, unauthenticated_async_client):
        response = await unauthenticated_async_client.get("/api/v1/settings/sessions")
        assert response.status_code in (401, 403)
