"""Tests for AgentState model."""

import pytest
from sqlalchemy import select

from models.agent_state import AgentState


class TestAgentStateModel:
    """Test AgentState database model."""

    @pytest.mark.asyncio
    async def test_create_agent_state(self, db_session, test_user):
        """Test creating a new agent state."""
        state = AgentState(
            user_id=test_user.id,
            agent_name="luna",
            soul_content="# Luna\nA friendly companion.",
        )
        db_session.add(state)
        await db_session.flush()

        assert state.id is not None
        assert state.user_id == test_user.id
        assert state.agent_name == "luna"
        assert state.soul_content == "# Luna\nA friendly companion."
        assert state.created_at is not None
        assert state.updated_at is not None

    @pytest.mark.asyncio
    async def test_unique_user_agent_constraint(self, db_session, test_user):
        """Test that user_id + agent_name must be unique."""
        state1 = AgentState(
            user_id=test_user.id,
            agent_name="luna",
        )
        db_session.add(state1)
        await db_session.flush()

        state2 = AgentState(
            user_id=test_user.id,
            agent_name="luna",
        )
        db_session.add(state2)

        with pytest.raises(Exception):  # IntegrityError
            await db_session.flush()

        # Rollback the failed transaction so the session stays usable
        await db_session.rollback()

    @pytest.mark.asyncio
    async def test_different_users_same_agent_name(self, db_session, test_user, other_user):
        """Test that different users can have agents with same name."""
        state1 = AgentState(
            user_id=test_user.id,
            agent_name="luna",
        )
        state2 = AgentState(
            user_id=other_user.id,
            agent_name="luna",
        )
        db_session.add(state1)
        db_session.add(state2)
        await db_session.flush()

        assert state1.id != state2.id

    @pytest.mark.asyncio
    async def test_query_by_user_and_agent_name(self, db_session, test_user):
        """Test querying agent state by user_id and agent_name."""
        state = AgentState(
            user_id=test_user.id,
            agent_name="rex",
            soul_content="# Rex\nA brave explorer.",
        )
        db_session.add(state)
        await db_session.flush()

        result = await db_session.execute(
            select(AgentState).where(
                AgentState.user_id == test_user.id,
                AgentState.agent_name == "rex",
            )
        )
        found = result.scalar_one_or_none()

        assert found is not None
        assert found.agent_name == "rex"
        assert found.soul_content == "# Rex\nA brave explorer."

    @pytest.mark.asyncio
    async def test_update_soul_content(self, db_session, test_user):
        """Test updating soul content."""
        state = AgentState(
            user_id=test_user.id,
            agent_name="luna",
            soul_content="# Original",
        )
        db_session.add(state)
        await db_session.flush()

        original_created = state.created_at

        # Update soul content
        state.soul_content = "# Updated personality"
        await db_session.flush()

        assert state.soul_content == "# Updated personality"
        assert state.created_at == original_created

    @pytest.mark.asyncio
    async def test_agent_without_soul_content(self, db_session, test_user):
        """Test creating agent without soul content."""
        state = AgentState(
            user_id=test_user.id,
            agent_name="minimal",
        )
        db_session.add(state)
        await db_session.flush()

        assert state.soul_content is None
        assert state.id is not None
