"""Tests for GooseTown router endpoints."""

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

        # Agents spawn in apartment with sprite_ready=False; set sprite_ready and move to town
        from sqlalchemy import update
        from models.town import TownAgent, TownState

        await db_session.execute(update(TownAgent).values(sprite_ready=True))
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

        # Agents spawn in apartment with sprite_ready=False; set sprite_ready and move to town
        from sqlalchemy import update
        from models.town import TownAgent, TownState

        await db_session.execute(update(TownAgent).values(sprite_ready=True))
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

    @pytest.mark.asyncio
    async def test_register_creates_background_sprite_task(self, async_client, db_session, test_user):
        """When appearance is provided with valid settings, a background sprite task is created."""
        from unittest.mock import patch, MagicMock

        token = await self._get_town_token(async_client)

        mock_settings = MagicMock()
        mock_settings.pixellab_api_key = "test-key"
        mock_settings.SPRITE_S3_BUCKET = "test-bucket"
        mock_settings.SPRITE_CDN_URL = "https://cdn.example.com"

        created_tasks = []

        def capture_task(coro):
            # Cancel immediately to avoid background work, but record the call
            task = MagicMock()
            coro.close()  # clean up the coroutine
            created_tasks.append(task)
            return task

        with (
            patch("core.config.settings", mock_settings),
            patch("asyncio.create_task", side_effect=capture_task),
        ):
            response = await async_client.post(
                "/api/v1/town/agent/register",
                json={
                    "agent_name": "pixel_agent",
                    "display_name": "Pixel Agent",
                    "appearance": "A blue robot with glowing eyes",
                },
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 200
        assert len(created_tasks) == 1  # background sprite task was created

    @pytest.mark.asyncio
    async def test_register_no_sprite_task_without_settings(self, async_client, db_session, test_user):
        """No background task created when SPRITE_S3_BUCKET is not configured."""
        from unittest.mock import patch, MagicMock

        token = await self._get_town_token(async_client)

        mock_settings = MagicMock()
        mock_settings.pixellab_api_key = "test-key"
        mock_settings.SPRITE_S3_BUCKET = ""  # not configured
        mock_settings.SPRITE_CDN_URL = ""

        with (
            patch("core.config.settings", mock_settings),
            patch("asyncio.create_task") as mock_create_task,
        ):
            response = await async_client.post(
                "/api/v1/town/agent/register",
                json={
                    "agent_name": "no_sprite",
                    "display_name": "No Sprite",
                    "appearance": "A wizard in purple robes",
                },
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 200
        mock_create_task.assert_not_called()


class TestAgentStatus:
    """Test GET /api/v1/town/agent/status (sprite polling)."""

    async def _get_town_token(self, async_client):
        resp = await async_client.post("/api/v1/town/instance")
        assert resp.status_code == 200
        return resp.json()["town_token"]

    @pytest.mark.asyncio
    async def test_status_404_unknown_agent(self, async_client, db_session, test_user):
        token = await self._get_town_token(async_client)
        response = await async_client.get(
            "/api/v1/town/agent/status",
            params={"agent_name": "nonexistent"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_status_not_ready_no_pixellab_id(self, async_client, db_session, test_user):
        token = await self._get_town_token(async_client)
        # Register agent without appearance (no pixellab_character_id)
        await async_client.post(
            "/api/v1/town/agent/register",
            json={"agent_name": "plain", "display_name": "Plain Agent"},
            headers={"Authorization": f"Bearer {token}"},
        )
        response = await async_client.get(
            "/api/v1/town/agent/status",
            params={"agent_name": "plain"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["agent_name"] == "plain"
        assert data["sprite_ready"] is False
        assert data["sprite_url"] is None

    @pytest.mark.asyncio
    async def test_status_cached_sprite(self, async_client, db_session, test_user):
        token = await self._get_town_token(async_client)
        await async_client.post(
            "/api/v1/town/agent/register",
            json={"agent_name": "cached", "display_name": "Cached Agent"},
            headers={"Authorization": f"Bearer {token}"},
        )
        # Manually set sprite_ready and sprite_url in DB
        from sqlalchemy import update
        from models.town import TownAgent

        await db_session.execute(
            update(TownAgent)
            .where(TownAgent.agent_name == "cached")
            .values(sprite_ready=True, sprite_url="https://cdn.example.com/sprites/test/walk.png")
        )
        await db_session.commit()

        response = await async_client.get(
            "/api/v1/town/agent/status",
            params={"agent_name": "cached"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["agent_name"] == "cached"
        assert data["sprite_ready"] is True
        assert data["sprite_url"] == "https://cdn.example.com/sprites/test/walk.png"

    @pytest.mark.asyncio
    async def test_status_polls_pixellab_and_uploads(self, async_client, db_session, test_user):
        token = await self._get_town_token(async_client)
        await async_client.post(
            "/api/v1/town/agent/register",
            json={"agent_name": "sprited", "display_name": "Sprited Agent"},
            headers={"Authorization": f"Bearer {token}"},
        )
        # Set pixellab_character_id so polling branch is triggered
        from sqlalchemy import update
        from models.town import TownAgent

        await db_session.execute(
            update(TownAgent).where(TownAgent.agent_name == "sprited").values(pixellab_character_id="pxl_char_123")
        )
        await db_session.commit()

        from unittest.mock import AsyncMock, patch, MagicMock

        fake_zip = b"fake-zip-bytes"
        fake_png = b"fake-png-bytes"
        mock_settings = MagicMock()
        mock_settings.pixellab_api_key = "test-key"
        mock_settings.SPRITE_S3_BUCKET = "test-bucket"
        mock_settings.SPRITE_CDN_URL = "https://cdn.example.com"

        mock_pxl_instance = AsyncMock()
        mock_pxl_instance.download_character_zip.return_value = fake_zip

        with (
            patch("core.config.settings", mock_settings),
            patch(
                "core.services.pixellab_service.PixelLabService",
                return_value=mock_pxl_instance,
            ),
            patch(
                "core.services.sprite_storage.extract_walk_spritesheet",
                return_value=fake_png,
            ) as mock_extract,
            patch(
                "core.services.sprite_storage.upload_sprite_to_s3",
                return_value="sprites/test-id/walk.png",
            ) as mock_upload,
        ):
            response = await async_client.get(
                "/api/v1/town/agent/status",
                params={"agent_name": "sprited"},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["agent_name"] == "sprited"
        assert data["sprite_ready"] is True
        assert data["sprite_url"] == "https://cdn.example.com/sprites/test-id/walk.png"
        mock_pxl_instance.download_character_zip.assert_called_once_with("pxl_char_123")
        mock_extract.assert_called_once_with(fake_zip)
        mock_upload.assert_called_once()


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
