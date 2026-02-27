"""Tests for Agent API endpoints."""

import pytest
from unittest.mock import MagicMock, patch


class TestAgentEndpoints:
    """Test agent REST API endpoints."""

    @pytest.mark.asyncio
    async def test_list_agents_empty(self, async_client, test_user):
        """Test listing agents when user has none."""
        response = await async_client.get("/api/v1/agents")
        assert response.status_code == 200
        data = response.json()
        assert data["agents"] == []

    @pytest.mark.asyncio
    @patch("routers.agents.get_container_manager")
    async def test_create_agent(self, mock_get_cm, async_client, test_user):
        """Test creating a new agent."""
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = None
        mock_get_cm.return_value = mock_cm

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
        assert data["user_id"] == test_user.id
        assert data["soul_content"] == "# Luna\nA friendly companion."

    @pytest.mark.asyncio
    @patch("routers.agents.get_container_manager")
    async def test_create_duplicate_agent(self, mock_get_cm, async_client, test_user):
        """Test creating duplicate agent fails."""
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = None
        mock_get_cm.return_value = mock_cm

        # Create first
        await async_client.post(
            "/api/v1/agents",
            json={"agent_name": "luna"},
        )

        # Try to create again
        response = await async_client.post(
            "/api/v1/agents",
            json={"agent_name": "luna"},
        )
        assert response.status_code == 409

    @pytest.mark.asyncio
    @patch("routers.agents.get_container_manager")
    async def test_get_agent(self, mock_get_cm, async_client, test_user):
        """Test getting agent details."""
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = None
        mock_get_cm.return_value = mock_cm

        # Create first
        await async_client.post(
            "/api/v1/agents",
            json={"agent_name": "luna"},
        )

        # Get details
        response = await async_client.get("/api/v1/agents/luna")
        assert response.status_code == 200
        data = response.json()
        assert data["agent_name"] == "luna"

    @pytest.mark.asyncio
    async def test_get_nonexistent_agent(self, async_client, test_user):
        """Test getting non-existent agent returns 404."""
        response = await async_client.get("/api/v1/agents/nonexistent")
        assert response.status_code == 404

    @pytest.mark.asyncio
    @patch("routers.agents.get_container_manager")
    async def test_delete_agent(self, mock_get_cm, async_client, test_user):
        """Test deleting an agent."""
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = None
        mock_get_cm.return_value = mock_cm

        # Create first
        await async_client.post(
            "/api/v1/agents",
            json={"agent_name": "luna"},
        )

        # Delete
        response = await async_client.delete("/api/v1/agents/luna")
        assert response.status_code == 204

        # Verify gone
        response = await async_client.get("/api/v1/agents/luna")
        assert response.status_code == 404

    @pytest.mark.asyncio
    @patch("routers.agents.get_container_manager")
    async def test_list_agents(self, mock_get_cm, async_client, test_user):
        """Test listing all user's agents."""
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = None
        mock_get_cm.return_value = mock_cm

        # Create multiple
        await async_client.post("/api/v1/agents", json={"agent_name": "luna"})
        await async_client.post("/api/v1/agents", json={"agent_name": "rex"})

        # List
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
