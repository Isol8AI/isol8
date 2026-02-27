"""Tests for AgentService business logic."""

import pytest

from core.services.agent_service import AgentService


class TestAgentService:
    """Test AgentService CRUD operations."""

    @pytest.fixture
    def service(self, db_session):
        """Create service instance."""
        return AgentService(db_session)

    @pytest.mark.asyncio
    async def test_get_agent_not_found(self, service, test_user):
        """Test getting non-existent agent returns None."""
        result = await service.get_agent(
            user_id=test_user.id,
            agent_name="nonexistent",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_create_agent(self, service, test_user):
        """Test creating new agent."""
        state = await service.create_agent(
            user_id=test_user.id,
            agent_name="luna",
            soul_content="# Luna\nA friendly companion.",
        )

        assert state is not None
        assert state.user_id == test_user.id
        assert state.agent_name == "luna"
        assert state.soul_content == "# Luna\nA friendly companion."

    @pytest.mark.asyncio
    async def test_create_agent_without_soul(self, service, test_user):
        """Test creating agent without soul content."""
        state = await service.create_agent(
            user_id=test_user.id,
            agent_name="minimal",
        )

        assert state is not None
        assert state.agent_name == "minimal"
        assert state.soul_content is None

    @pytest.mark.asyncio
    async def test_get_agent(self, service, test_user):
        """Test getting existing agent."""
        await service.create_agent(
            user_id=test_user.id,
            agent_name="luna",
            soul_content="# Luna",
        )

        state = await service.get_agent(
            user_id=test_user.id,
            agent_name="luna",
        )

        assert state is not None
        assert state.agent_name == "luna"

    @pytest.mark.asyncio
    async def test_list_agents(self, service, test_user):
        """Test listing all agents for a user."""
        await service.create_agent(
            user_id=test_user.id,
            agent_name="luna",
        )
        await service.create_agent(
            user_id=test_user.id,
            agent_name="rex",
        )

        agents = await service.list_agents(user_id=test_user.id)

        assert len(agents) == 2
        agent_names = [a.agent_name for a in agents]
        assert "luna" in agent_names
        assert "rex" in agent_names

    @pytest.mark.asyncio
    async def test_delete_agent(self, service, test_user):
        """Test deleting agent."""
        await service.create_agent(
            user_id=test_user.id,
            agent_name="luna",
        )

        deleted = await service.delete_agent(
            user_id=test_user.id,
            agent_name="luna",
        )

        assert deleted is True

        # Verify it's gone
        state = await service.get_agent(
            user_id=test_user.id,
            agent_name="luna",
        )
        assert state is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_agent(self, service, test_user):
        """Test deleting non-existent agent returns False."""
        deleted = await service.delete_agent(
            user_id=test_user.id,
            agent_name="nonexistent",
        )
        assert deleted is False

    @pytest.mark.asyncio
    async def test_user_isolation(self, service, test_user, other_user):
        """Test that users can't access each other's agents."""
        await service.create_agent(
            user_id=test_user.id,
            agent_name="luna",
        )

        # Other user shouldn't see it
        state = await service.get_agent(
            user_id=other_user.id,
            agent_name="luna",
        )
        assert state is None

        # Other user's list should be empty
        agents = await service.list_agents(user_id=other_user.id)
        assert len(agents) == 0

    @pytest.mark.asyncio
    async def test_update_soul_content(self, service, test_user):
        """Test updating agent soul content."""
        await service.create_agent(
            user_id=test_user.id,
            agent_name="luna",
            soul_content="# Original",
        )

        updated = await service.update_soul_content(
            user_id=test_user.id,
            agent_name="luna",
            soul_content="# Updated personality",
        )

        assert updated is not None
        assert updated.soul_content == "# Updated personality"

    @pytest.mark.asyncio
    async def test_update_soul_content_not_found(self, service, test_user):
        """Test updating non-existent agent returns None."""
        result = await service.update_soul_content(
            user_id=test_user.id,
            agent_name="nonexistent",
            soul_content="# Does not exist",
        )
        assert result is None
