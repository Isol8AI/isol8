"""Tests for Bit City router endpoints."""

import pytest


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
    async def test_get_state_with_agents(self, async_client, db_session, test_user):
        # Create instance via the instance endpoint
        inst_resp = await async_client.post("/api/v1/town/instance")
        assert inst_resp.status_code == 200
        token = inst_resp.json()["town_token"]

        # Register an agent
        await async_client.post(
            "/api/v1/town/agent/register",
            json={"agent_name": "luna", "display_name": "Luna"},
            headers={"Authorization": f"Bearer {token}"},
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
    async def test_get_descriptions_with_agents(self, async_client, db_session, test_user):
        # Create instance and register agent
        inst_resp = await async_client.post("/api/v1/town/instance")
        assert inst_resp.status_code == 200
        token = inst_resp.json()["town_token"]

        await async_client.post(
            "/api/v1/town/agent/register",
            json={
                "agent_name": "luna",
                "display_name": "Luna",
                "personality": "A dreamer",
            },
            headers={"Authorization": f"Bearer {token}"},
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

    async def _get_town_token(self, async_client):
        """Create an instance and return the town_token."""
        resp = await async_client.post("/api/v1/town/instance")
        assert resp.status_code == 200
        return resp.json()["town_token"]

    @pytest.mark.asyncio
    async def test_register_success(self, async_client, db_session, test_user):
        token = await self._get_town_token(async_client)

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
    async def test_register_duplicate_name(self, async_client, db_session, test_user):
        token = await self._get_town_token(async_client)

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
    async def test_register_invalid_token(self, async_client, db_session, test_user):
        response = await async_client.post(
            "/api/v1/town/agent/register",
            json={"agent_name": "atlas", "display_name": "Atlas"},
            headers={"Authorization": "Bearer invalid_token"},
        )

        assert response.status_code == 401


class TestTownApartment:
    """Test GET /api/v1/town/apartment."""

    @pytest.mark.asyncio
    async def test_apartment_empty(self, async_client, db_session, test_user):
        response = await async_client.get("/api/v1/town/apartment")
        assert response.status_code == 200
        data = response.json()
        assert data["agents"] == []
        assert data["activity"] == []

    @pytest.mark.asyncio
    async def test_apartment_agent_without_state(self, async_client, db_session, test_user):
        """Agent with no TownState row should not cause 500."""
        from models.town import TownAgent

        agent = TownAgent(
            user_id="user_test_123",
            agent_name="orphan",
            display_name="Orphan Agent",
        )
        db_session.add(agent)
        await db_session.flush()

        response = await async_client.get("/api/v1/town/apartment")
        assert response.status_code == 200
        data = response.json()
        assert len(data["agents"]) == 1
        assert data["agents"][0]["agent_name"] == "orphan"
        # Defaults should be used when state is None
        assert data["agents"][0]["energy"] == 100
        assert data["agents"][0]["position_x"] == 0.0

    @pytest.mark.asyncio
    async def test_apartment_agent_with_null_state_fields(self, async_client, db_session, test_user):
        """Agent with TownState that has NULL optional fields should not cause 500."""
        from models.town import TownAgent

        agent = TownAgent(
            user_id="user_test_123",
            agent_name="nullish",
            display_name="Nullish Agent",
        )
        db_session.add(agent)
        await db_session.flush()

        # Create state with NULL values for fields that have Python defaults but
        # are nullable in DB (speed, facing_x, facing_y)
        from sqlalchemy import text

        await db_session.execute(
            text(
                "INSERT INTO town_state (id, agent_id, position_x, position_y, energy, speed, facing_x, facing_y) "
                "VALUES (gen_random_uuid(), :agent_id, 2.0, 6.0, 100, NULL, NULL, NULL)"
            ),
            {"agent_id": agent.id},
        )
        await db_session.flush()

        response = await async_client.get("/api/v1/town/apartment")
        assert response.status_code == 200
        data = response.json()
        assert len(data["agents"]) == 1
        assert data["agents"][0]["agent_name"] == "nullish"

    @pytest.mark.asyncio
    async def test_apartment_with_agents(self, async_client, db_session, test_user):
        # Create instance and register agent
        inst_resp = await async_client.post("/api/v1/town/instance")
        assert inst_resp.status_code == 200
        token = inst_resp.json()["town_token"]

        await async_client.post(
            "/api/v1/town/agent/register",
            json={"agent_name": "luna", "display_name": "Luna"},
            headers={"Authorization": f"Bearer {token}"},
        )

        response = await async_client.get("/api/v1/town/apartment")
        assert response.status_code == 200
        data = response.json()
        assert len(data["agents"]) == 1
        assert data["agents"][0]["agent_name"] == "luna"
