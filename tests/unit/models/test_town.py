"""Tests for GooseTown database models."""

import pytest

from models.town import TownAgent, TownInstance, TownState, TownConversation, TownRelationship


class TestTownInstanceModel:
    """Test TownInstance database model."""

    @pytest.mark.asyncio
    async def test_create_town_instance(self, db_session):
        instance = TownInstance(
            user_id="user_inst_1",
            apartment_unit=1,
            town_token="tok_test_1",
        )
        db_session.add(instance)
        await db_session.flush()

        assert instance.id is not None
        assert instance.user_id == "user_inst_1"
        assert instance.apartment_unit == 1
        assert instance.is_active is True

    @pytest.mark.asyncio
    async def test_multiple_instances_per_user(self, db_session):
        """user_id is NOT unique — allows re-opt-in after opt-out."""
        i1 = TownInstance(user_id="user_dup", apartment_unit=1, town_token="tok_1")
        i2 = TownInstance(user_id="user_dup", apartment_unit=2, town_token="tok_2")
        db_session.add(i1)
        await db_session.flush()
        db_session.add(i2)
        await db_session.flush()

        assert i1.id != i2.id

    @pytest.mark.asyncio
    async def test_unique_apartment_unit(self, db_session):
        i1 = TownInstance(user_id="user_a1", apartment_unit=1, town_token="tok_a1")
        i2 = TownInstance(user_id="user_a2", apartment_unit=1, town_token="tok_a2")
        db_session.add(i1)
        await db_session.flush()
        db_session.add(i2)

        with pytest.raises(Exception):
            await db_session.flush()

        await db_session.rollback()

    @pytest.mark.asyncio
    async def test_unique_town_token(self, db_session):
        i1 = TownInstance(user_id="user_t1", apartment_unit=1, town_token="tok_shared")
        i2 = TownInstance(user_id="user_t2", apartment_unit=2, town_token="tok_shared")
        db_session.add(i1)
        await db_session.flush()
        db_session.add(i2)

        with pytest.raises(Exception):
            await db_session.flush()

        await db_session.rollback()


class TestTownAgentModel:
    """Test TownAgent database model."""

    @pytest.mark.asyncio
    async def test_create_town_agent(self, db_session, test_user):
        agent = TownAgent(
            user_id=test_user.id,
            agent_name="luna",
            display_name="Luna the Dreamer",
            personality_summary="A curious bookworm who loves stargazing",
        )
        db_session.add(agent)
        await db_session.flush()

        assert agent.id is not None
        assert agent.user_id == test_user.id
        assert agent.agent_name == "luna"
        assert agent.display_name == "Luna the Dreamer"
        assert agent.is_active is True
        assert agent.joined_at is not None

    @pytest.mark.asyncio
    async def test_unique_user_agent_constraint(self, db_session, test_user):
        agent1 = TownAgent(
            user_id=test_user.id,
            agent_name="luna",
            display_name="Luna",
        )
        db_session.add(agent1)
        await db_session.flush()

        agent2 = TownAgent(
            user_id=test_user.id,
            agent_name="luna",
            display_name="Luna Copy",
        )
        db_session.add(agent2)

        with pytest.raises(Exception):
            await db_session.flush()

        await db_session.rollback()

    @pytest.mark.asyncio
    async def test_different_users_same_agent_name(self, db_session, test_user, other_user):
        agent1 = TownAgent(user_id=test_user.id, agent_name="luna", display_name="Luna A")
        agent2 = TownAgent(user_id=other_user.id, agent_name="luna", display_name="Luna B")
        db_session.add(agent1)
        db_session.add(agent2)
        await db_session.flush()

        assert agent1.id != agent2.id


class TestTownStateModel:
    """Test TownState database model."""

    @pytest.mark.asyncio
    async def test_create_town_state(self, db_session, test_user):
        agent = TownAgent(user_id=test_user.id, agent_name="rex", display_name="Rex")
        db_session.add(agent)
        await db_session.flush()

        state = TownState(
            agent_id=agent.id,
            current_location="cafe",
            current_activity="idle",
            position_x=100.0,
            position_y=200.0,
            energy=80,
        )
        db_session.add(state)
        await db_session.flush()

        assert state.id is not None
        assert state.agent_id == agent.id
        assert state.current_location == "cafe"
        assert state.energy == 80

    @pytest.mark.asyncio
    async def test_default_energy(self, db_session, test_user):
        agent = TownAgent(user_id=test_user.id, agent_name="rex", display_name="Rex")
        db_session.add(agent)
        await db_session.flush()

        state = TownState(agent_id=agent.id, position_x=0.0, position_y=0.0)
        db_session.add(state)
        await db_session.flush()

        assert state.energy == 100
        assert state.current_activity == "idle"

    @pytest.mark.asyncio
    async def test_state_location_state_default(self, db_session, test_user):
        agent = TownAgent(user_id=test_user.id, agent_name="loc_test", display_name="LocTest")
        db_session.add(agent)
        await db_session.flush()

        state = TownState(agent_id=agent.id, position_x=0.0, position_y=0.0)
        db_session.add(state)
        await db_session.flush()

        assert state.location_state == "sleeping"
        assert state.target_x is None
        assert state.target_y is None
        assert state.facing_x == 0.0
        assert state.facing_y == 1.0
        assert state.speed == 0.0
        assert state.current_conversation_id is None
        assert state.last_heartbeat_at is None


class TestTownConversationModel:
    """Test TownConversation database model."""

    @pytest.mark.asyncio
    async def test_create_conversation(self, db_session, test_user, other_user):
        agent_a = TownAgent(user_id=test_user.id, agent_name="luna", display_name="Luna")
        agent_b = TownAgent(user_id=other_user.id, agent_name="rex", display_name="Rex")
        db_session.add(agent_a)
        db_session.add(agent_b)
        await db_session.flush()

        convo = TownConversation(
            participant_a_id=agent_a.id,
            participant_b_id=agent_b.id,
            location="plaza",
            turn_count=3,
            topic_summary="Discussed favorite books",
            public_log=[
                {"speaker": "Luna", "text": "Have you read anything good lately?"},
                {"speaker": "Rex", "text": "I just finished a great mystery novel!"},
                {"speaker": "Luna", "text": "Oh, I love mysteries too!"},
            ],
        )
        db_session.add(convo)
        await db_session.flush()

        assert convo.id is not None
        assert convo.turn_count == 3
        assert len(convo.public_log) == 3

    @pytest.mark.asyncio
    async def test_conversation_status_default(self, db_session, test_user, other_user):
        agent_a = TownAgent(user_id=test_user.id, agent_name="cs_a", display_name="A")
        agent_b = TownAgent(user_id=other_user.id, agent_name="cs_b", display_name="B")
        db_session.add_all([agent_a, agent_b])
        await db_session.flush()

        convo = TownConversation(participant_a_id=agent_a.id, participant_b_id=agent_b.id)
        db_session.add(convo)
        await db_session.flush()

        assert convo.status == "pending"
        assert convo.waiting_for is None


class TestTownRelationshipModel:
    """Test TownRelationship database model."""

    @pytest.mark.asyncio
    async def test_create_relationship(self, db_session, test_user, other_user):
        agent_a = TownAgent(user_id=test_user.id, agent_name="luna", display_name="Luna")
        agent_b = TownAgent(user_id=other_user.id, agent_name="rex", display_name="Rex")
        db_session.add(agent_a)
        db_session.add(agent_b)
        await db_session.flush()

        rel = TownRelationship(
            agent_a_id=agent_a.id,
            agent_b_id=agent_b.id,
        )
        db_session.add(rel)
        await db_session.flush()

        assert rel.affinity_score == 0
        assert rel.interaction_count == 0
        assert rel.relationship_type == "stranger"

    @pytest.mark.asyncio
    async def test_unique_relationship_constraint(self, db_session, test_user, other_user):
        agent_a = TownAgent(user_id=test_user.id, agent_name="luna", display_name="Luna")
        agent_b = TownAgent(user_id=other_user.id, agent_name="rex", display_name="Rex")
        db_session.add(agent_a)
        db_session.add(agent_b)
        await db_session.flush()

        rel1 = TownRelationship(agent_a_id=agent_a.id, agent_b_id=agent_b.id)
        db_session.add(rel1)
        await db_session.flush()

        rel2 = TownRelationship(agent_a_id=agent_a.id, agent_b_id=agent_b.id)
        db_session.add(rel2)

        with pytest.raises(Exception):
            await db_session.flush()

        await db_session.rollback()
