"""Tests for GooseTown router endpoints."""

import pytest
from unittest.mock import MagicMock

from core.services.town_skill import TownSkillService
from routers.town import get_skill_service


@pytest.fixture
def mock_skill_service(app):
    """Override get_skill_service with a no-op mock."""
    mock_svc = MagicMock(spec=TownSkillService)
    app.dependency_overrides[get_skill_service] = lambda: mock_svc
    yield mock_svc
    app.dependency_overrides.pop(get_skill_service, None)


class TestTownOptIn:
    """Test POST /api/v1/town/opt-in (instance-based)."""

    @pytest.mark.asyncio
    async def test_opt_in_success(self, async_client, db_session, test_user, mock_skill_service):
        response = await async_client.post(
            "/api/v1/town/opt-in",
            json={
                "agents": [
                    {
                        "agent_name": "luna",
                        "display_name": "Luna the Dreamer",
                        "personality_summary": "A curious bookworm",
                    }
                ]
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert "instance_id" in data
        assert "town_token" in data
        assert data["apartment_unit"] == 1
        assert len(data["agents"]) == 1
        assert data["agents"][0]["agent_name"] == "luna"
        assert data["agents"][0]["display_name"] == "Luna the Dreamer"
        assert data["agents"][0]["is_active"] is True


class TestTownOptOut:
    """Test POST /api/v1/town/opt-out (instance-based)."""

    @pytest.mark.asyncio
    async def test_opt_out_success(self, async_client, db_session, test_user, mock_skill_service):
        await async_client.post(
            "/api/v1/town/opt-in",
            json={"agents": [{"agent_name": "luna", "display_name": "Luna"}]},
        )

        response = await async_client.post("/api/v1/town/opt-out")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "opted_out"
        assert data["deactivated_agents"] == 1

    @pytest.mark.asyncio
    async def test_opt_out_not_found(self, async_client, test_user, mock_skill_service):
        response = await async_client.post("/api/v1/town/opt-out")

        assert response.status_code == 404


class TestTownStatus:
    """Test GET /api/v1/town/status (AI Town worldStatus)."""

    @pytest.mark.asyncio
    async def test_get_status(self, async_client):
        response = await async_client.get("/api/v1/town/status")

        assert response.status_code == 200
        data = response.json()
        assert data["worldId"] == "world_default"
        assert data["engineId"] == "engine_default"
        assert data["status"] == "running"
        assert data["isDefault"] is True


class TestTownState:
    """Test GET /api/v1/town/state (AI Town worldState format)."""

    @pytest.mark.asyncio
    async def test_get_state_defaults(self, async_client):
        response = await async_client.get("/api/v1/town/state")

        assert response.status_code == 200
        data = response.json()
        assert data["world"]["players"] == []
        assert data["world"]["agents"] == []
        assert data["world"]["conversations"] == []
        assert "currentTime" in data["engine"]

    @pytest.mark.asyncio
    async def test_get_state_with_agents(self, async_client, db_session, test_user, mock_skill_service):
        await async_client.post(
            "/api/v1/town/opt-in",
            json={"agents": [{"agent_name": "luna", "display_name": "Luna"}]},
        )

        # Agents spawn in apartment; move to town context so they appear in /state
        from sqlalchemy import update
        from models.town import TownState

        await db_session.execute(update(TownState).values(location_context="town"))
        await db_session.commit()

        response = await async_client.get("/api/v1/town/state")

        assert response.status_code == 200
        data = response.json()
        assert len(data["world"]["players"]) == 1
        assert data["world"]["players"][0]["id"] == "p:0"
        assert "position" in data["world"]["players"][0]
        assert len(data["world"]["agents"]) == 1
        assert data["world"]["agents"][0]["id"] == "a:0"
        assert data["world"]["agents"][0]["playerId"] == "p:0"


class TestTownDescriptions:
    """Test GET /api/v1/town/descriptions (AI Town gameDescriptions)."""

    @pytest.mark.asyncio
    async def test_get_descriptions_defaults(self, async_client):
        response = await async_client.get("/api/v1/town/descriptions")

        assert response.status_code == 200
        data = response.json()
        assert "worldMap" in data
        assert data["worldMap"]["width"] > 0
        assert data["playerDescriptions"] == []
        assert data["agentDescriptions"] == []

    @pytest.mark.asyncio
    async def test_get_descriptions_with_agents(self, async_client, db_session, test_user, mock_skill_service):
        await async_client.post(
            "/api/v1/town/opt-in",
            json={
                "agents": [
                    {
                        "agent_name": "luna",
                        "display_name": "Luna",
                        "personality_summary": "A dreamer",
                    }
                ]
            },
        )

        # Agents spawn in apartment; move to town context so they appear in /descriptions
        from sqlalchemy import update
        from models.town import TownState

        await db_session.execute(update(TownState).values(location_context="town"))
        await db_session.commit()

        response = await async_client.get("/api/v1/town/descriptions")

        assert response.status_code == 200
        data = response.json()
        assert len(data["playerDescriptions"]) == 1
        assert data["playerDescriptions"][0]["name"] == "Luna"
        assert data["playerDescriptions"][0]["playerId"] == "p:0"
        assert len(data["agentDescriptions"]) == 1
        assert data["agentDescriptions"][0]["agentId"] == "a:0"


class TestTownConversations:
    """Test GET /api/v1/town/conversations."""

    @pytest.mark.asyncio
    async def test_get_conversations_empty(self, async_client):
        response = await async_client.get("/api/v1/town/conversations")

        assert response.status_code == 200
        data = response.json()
        assert data["conversations"] == []


class TestAgentRegister:
    """Test POST /api/v1/town/agent/register (town_token auth)."""

    async def _get_town_token(self, async_client, mock_skill_service):
        """Opt-in and return the town_token."""
        resp = await async_client.post(
            "/api/v1/town/opt-in",
            json={"agents": [{"agent_name": "seed", "display_name": "Seed Agent"}]},
        )
        assert resp.status_code == 201
        return resp.json()["town_token"]

    @pytest.mark.asyncio
    async def test_register_success(self, async_client, db_session, test_user, mock_skill_service):
        token = await self._get_town_token(async_client, mock_skill_service)

        response = await async_client.post(
            "/api/v1/town/agent/register",
            json={
                "agent_name": "atlas",
                "display_name": "Atlas the Explorer",
                "personality": "Brave and curious",
                "appearance": "Tall with a red hat",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["agent_name"] == "atlas"
        assert data["display_name"] == "Atlas the Explorer"
        assert data["character"] == "c6"
        assert data["position"] == {"x": 9.0, "y": 6.0}
        assert data["status"] == "generating_sprite"
        assert "ws_url" in data
        assert "api_url" in data
        assert "Welcome" in data["message"]

    @pytest.mark.asyncio
    async def test_register_duplicate_name(self, async_client, db_session, test_user, mock_skill_service):
        token = await self._get_town_token(async_client, mock_skill_service)

        # Register first agent
        await async_client.post(
            "/api/v1/town/agent/register",
            json={"agent_name": "atlas", "display_name": "Atlas"},
            headers={"Authorization": f"Bearer {token}"},
        )

        # Try duplicate
        response = await async_client.post(
            "/api/v1/town/agent/register",
            json={"agent_name": "atlas", "display_name": "Atlas 2"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 400
        assert "already registered" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_register_invalid_token(self, async_client, db_session, test_user, mock_skill_service):
        response = await async_client.post(
            "/api/v1/town/agent/register",
            json={"agent_name": "atlas", "display_name": "Atlas"},
            headers={"Authorization": "Bearer invalid_token"},
        )

        assert response.status_code == 401


class TestTownApartment:
    """Test GET /api/v1/town/apartment."""

    @pytest.mark.asyncio
    async def test_apartment_empty(self, async_client, db_session, test_user, mock_skill_service):
        response = await async_client.get("/api/v1/town/apartment")
        assert response.status_code == 200
        data = response.json()
        assert data["agents"] == []
        assert data["activity"] == []

    @pytest.mark.asyncio
    async def test_apartment_with_agents(self, async_client, db_session, test_user, mock_skill_service):
        await async_client.post(
            "/api/v1/town/opt-in",
            json={"agents": [{"agent_name": "luna", "display_name": "Luna"}]},
        )

        response = await async_client.get("/api/v1/town/apartment")
        assert response.status_code == 200
        data = response.json()
        assert len(data["agents"]) == 1
        assert data["agents"][0]["agent_name"] == "luna"
