"""Tests for Agent API endpoints (EFS workspace-backed)."""

import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

from core.containers.workspace import WorkspaceError


class TestAgentEndpoints:
    """Test agent REST API endpoints."""

    @pytest.mark.asyncio
    @patch("routers.agents.get_workspace")
    async def test_list_agents_empty(self, mock_get_ws, async_client, test_user):
        """Test listing agents when user has none."""
        mock_ws = MagicMock()
        mock_ws.list_agents.return_value = []
        mock_get_ws.return_value = mock_ws

        response = await async_client.get("/api/v1/agents")
        assert response.status_code == 200
        data = response.json()
        assert data["agents"] == []
        mock_ws.list_agents.assert_called_once_with("user_test_123")

    @pytest.mark.asyncio
    @patch("routers.agents.get_workspace")
    async def test_create_agent(self, mock_get_ws, async_client, test_user):
        """Test creating a new agent."""
        mock_ws = MagicMock()
        mock_ws.list_agents.return_value = []
        mock_get_ws.return_value = mock_ws

        response = await async_client.post(
            "/api/v1/agents",
            json={
                "agent_name": "luna",
                "soul_content": "# Luna\nA friendly companion.",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["agent_name"] == "luna"
        assert data["soul_content"] == "# Luna\nA friendly companion."

        mock_ws.ensure_user_dir.assert_called_once_with("user_test_123")
        mock_ws.write_file.assert_called_once_with(
            "user_test_123",
            "agents/luna/SOUL.md",
            "# Luna\nA friendly companion.",
        )

    @pytest.mark.asyncio
    @patch("routers.agents.get_workspace")
    async def test_create_agent_no_soul(self, mock_get_ws, async_client, test_user):
        """Test creating an agent without soul content."""
        mock_ws = MagicMock()
        mock_ws.list_agents.return_value = []
        mock_get_ws.return_value = mock_ws

        response = await async_client.post(
            "/api/v1/agents",
            json={"agent_name": "luna"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["agent_name"] == "luna"
        assert data["soul_content"] is None

        mock_ws.write_file.assert_called_once_with(
            "user_test_123",
            "agents/luna/SOUL.md",
            "",
        )

    @pytest.mark.asyncio
    @patch("routers.agents.get_workspace")
    async def test_create_duplicate_agent(self, mock_get_ws, async_client, test_user):
        """Test creating duplicate agent fails."""
        mock_ws = MagicMock()
        mock_ws.list_agents.return_value = ["luna"]
        mock_get_ws.return_value = mock_ws

        response = await async_client.post(
            "/api/v1/agents",
            json={"agent_name": "luna"},
        )
        assert response.status_code == 409

    @pytest.mark.asyncio
    @patch("routers.agents.get_workspace")
    async def test_get_agent(self, mock_get_ws, async_client, test_user):
        """Test getting agent details."""
        mock_ws = MagicMock()
        mock_ws.list_agents.return_value = ["luna"]
        mock_ws.read_file.return_value = "# Luna\nA friendly companion."
        mock_get_ws.return_value = mock_ws

        response = await async_client.get("/api/v1/agents/luna")
        assert response.status_code == 200
        data = response.json()
        assert data["agent_name"] == "luna"
        assert data["soul_content"] == "# Luna\nA friendly companion."

        mock_ws.read_file.assert_called_once_with(
            "user_test_123",
            "agents/luna/SOUL.md",
        )

    @pytest.mark.asyncio
    @patch("routers.agents.get_workspace")
    async def test_get_agent_no_soul(self, mock_get_ws, async_client, test_user):
        """Test getting agent that exists but has no SOUL.md."""
        mock_ws = MagicMock()
        mock_ws.list_agents.return_value = ["luna"]
        mock_ws.read_file.side_effect = WorkspaceError("File not found")
        mock_get_ws.return_value = mock_ws

        response = await async_client.get("/api/v1/agents/luna")
        assert response.status_code == 200
        data = response.json()
        assert data["agent_name"] == "luna"
        assert data["soul_content"] is None

    @pytest.mark.asyncio
    @patch("routers.agents.get_workspace")
    async def test_get_nonexistent_agent(self, mock_get_ws, async_client, test_user):
        """Test getting non-existent agent returns 404."""
        mock_ws = MagicMock()
        mock_ws.list_agents.return_value = []
        mock_get_ws.return_value = mock_ws

        response = await async_client.get("/api/v1/agents/nonexistent")
        assert response.status_code == 404

    @pytest.mark.asyncio
    @patch("routers.agents.get_workspace")
    async def test_update_agent(self, mock_get_ws, async_client, test_user):
        """Test updating agent SOUL.md."""
        mock_ws = MagicMock()
        mock_ws.list_agents.return_value = ["luna"]
        mock_get_ws.return_value = mock_ws

        response = await async_client.put(
            "/api/v1/agents/luna",
            json={"soul_content": "# Luna v2\nUpdated personality."},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["agent_name"] == "luna"
        assert data["soul_content"] == "# Luna v2\nUpdated personality."

        mock_ws.write_file.assert_called_once_with(
            "user_test_123",
            "agents/luna/SOUL.md",
            "# Luna v2\nUpdated personality.",
        )

    @pytest.mark.asyncio
    @patch("routers.agents.get_workspace")
    async def test_update_nonexistent_agent(self, mock_get_ws, async_client, test_user):
        """Test updating non-existent agent returns 404."""
        mock_ws = MagicMock()
        mock_ws.list_agents.return_value = []
        mock_get_ws.return_value = mock_ws

        response = await async_client.put(
            "/api/v1/agents/nonexistent",
            json={"soul_content": "new content"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    @patch("routers.agents.shutil")
    @patch("routers.agents.get_workspace")
    async def test_delete_agent(self, mock_get_ws, mock_shutil, async_client, test_user):
        """Test deleting an agent."""
        mock_ws = MagicMock()
        mock_ws.list_agents.return_value = ["luna"]
        mock_ws._resolve_user_file.return_value = Path("/mnt/efs/user_test_123/agents/luna")
        mock_get_ws.return_value = mock_ws

        response = await async_client.delete("/api/v1/agents/luna")
        assert response.status_code == 204

        mock_ws._resolve_user_file.assert_called_once_with("user_test_123", "agents/luna")
        mock_shutil.rmtree.assert_called_once_with(Path("/mnt/efs/user_test_123/agents/luna"))

    @pytest.mark.asyncio
    @patch("routers.agents.get_workspace")
    async def test_delete_nonexistent_agent(self, mock_get_ws, async_client, test_user):
        """Test deleting non-existent agent returns 404."""
        mock_ws = MagicMock()
        mock_ws.list_agents.return_value = []
        mock_get_ws.return_value = mock_ws

        response = await async_client.delete("/api/v1/agents/nonexistent")
        assert response.status_code == 404

    @pytest.mark.asyncio
    @patch("routers.agents.get_workspace")
    async def test_list_agents(self, mock_get_ws, async_client, test_user):
        """Test listing all user's agents."""
        mock_ws = MagicMock()
        mock_ws.list_agents.return_value = ["luna", "rex"]
        mock_get_ws.return_value = mock_ws

        response = await async_client.get("/api/v1/agents")
        assert response.status_code == 200
        data = response.json()
        assert len(data["agents"]) == 2
        agent_names = [a["agent_name"] for a in data["agents"]]
        assert "luna" in agent_names
        assert "rex" in agent_names


class TestAgentAuthorization:
    """Test agent authorization."""

    @pytest.mark.asyncio
    async def test_unauthenticated_list_agents(self, unauthenticated_async_client):
        """Test that unauthenticated users can't list agents."""
        response = await unauthenticated_async_client.get("/api/v1/agents")
        # Server returns 403 Forbidden for unauthenticated requests
        assert response.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_unauthenticated_create_agent(self, unauthenticated_async_client):
        """Test that unauthenticated users can't create agents."""
        response = await unauthenticated_async_client.post(
            "/api/v1/agents",
            json={"agent_name": "luna"},
        )
        # Server returns 403 Forbidden for unauthenticated requests
        assert response.status_code in (401, 403)


class TestAgentValidation:
    """Test input validation for agent endpoints."""

    @pytest.mark.asyncio
    async def test_invalid_agent_name_special_chars(self, async_client, test_user):
        """Test that agent names with invalid characters are rejected."""
        response = await async_client.post(
            "/api/v1/agents",
            json={"agent_name": "luna@bot!"},
        )
        assert response.status_code == 422  # Validation error

    @pytest.mark.asyncio
    async def test_invalid_agent_name_too_long(self, async_client, test_user):
        """Test that agent names that are too long are rejected."""
        response = await async_client.post(
            "/api/v1/agents",
            json={"agent_name": "a" * 51},  # Max is 50
        )
        assert response.status_code == 422  # Validation error

    @pytest.mark.asyncio
    async def test_invalid_agent_name_empty(self, async_client, test_user):
        """Test that empty agent names are rejected."""
        response = await async_client.post(
            "/api/v1/agents",
            json={"agent_name": ""},
        )
        assert response.status_code == 422  # Validation error
