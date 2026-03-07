"""Town service for managing GooseTown agent registration and state."""

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.town_token import sign_town_token
from models.town import TownAgent, TownInstance, TownState, TownConversation, TownRelationship

logger = logging.getLogger(__name__)


class TownService:
    """Service for GooseTown CRUD operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def opt_in(
        self,
        user_id: str,
        agent_name: str,
        display_name: str,
        personality_summary: Optional[str] = None,
        avatar_config: Optional[dict] = None,
    ) -> TownAgent:
        """Register an agent in GooseTown.

        Agent name validation is the caller's responsibility (agents now
        live on EFS, so there is no DB-side AgentState to check).
        """
        existing = await self._get_town_agent(user_id, agent_name)
        if existing:
            if not existing.is_active:
                existing.is_active = True
                existing.display_name = display_name
                existing.personality_summary = personality_summary
                existing.avatar_config = avatar_config
                existing.last_active_at = datetime.now(timezone.utc)
                await self.db.flush()
                return existing
            return existing

        from core.apartment_constants import APARTMENT_SPOTS

        bedroom = APARTMENT_SPOTS["bed_1"]

        town_agent = TownAgent(
            user_id=user_id,
            agent_name=agent_name,
            display_name=display_name,
            personality_summary=personality_summary,
            avatar_config=avatar_config,
            home_location="apartment",
        )
        self.db.add(town_agent)
        await self.db.flush()

        state = TownState(
            agent_id=town_agent.id,
            position_x=float(bedroom["x"]),
            position_y=float(bedroom["y"]),
            current_location="bedroom",
            location_context="apartment",
        )
        self.db.add(state)
        await self.db.flush()

        logger.info(f"Agent '{agent_name}' opted into GooseTown as '{display_name}'")
        return town_agent

    async def opt_out(self, user_id: str, agent_name: str) -> bool:
        """Remove an agent from GooseTown (deactivate, preserve data)."""
        agent = await self._get_town_agent(user_id, agent_name)
        if not agent:
            return False

        agent.is_active = False
        await self.db.flush()
        logger.info(f"Agent '{agent_name}' opted out of GooseTown")
        return True

    async def get_active_agents(self) -> List[TownAgent]:
        """Get all active town agents."""
        result = await self.db.execute(
            select(TownAgent).where(TownAgent.is_active.is_(True)).order_by(TownAgent.joined_at)
        )
        return list(result.scalars().all())

    async def get_town_state(self) -> List[dict]:
        """Get current state of all active agents."""
        result = await self.db.execute(
            select(TownAgent, TownState)
            .join(TownState, TownState.agent_id == TownAgent.id)
            .where(TownAgent.is_active.is_(True))
        )
        rows = result.all()

        return [
            {
                "agent_id": agent.id,
                "user_id": agent.user_id,
                "display_name": agent.display_name,
                "agent_name": agent.agent_name,
                "character": agent.character,
                "personality_summary": agent.personality_summary,
                "home_location": agent.home_location,
                "current_location": state.current_location,
                "current_activity": state.current_activity,
                "target_location": state.target_location,
                "target_x": state.target_x,
                "target_y": state.target_y,
                "position_x": state.position_x,
                "position_y": state.position_y,
                "location_state": state.location_state,
                "location_context": state.location_context,
                "speed": state.speed,
                "facing_x": state.facing_x,
                "facing_y": state.facing_y,
                "current_conversation_id": state.current_conversation_id,
                "last_heartbeat_at": state.last_heartbeat_at,
                "mood": state.mood,
                "energy": state.energy,
                "status_message": state.status_message,
                "last_decision_at": state.last_decision_at,
                "last_conversation_at": state.last_conversation_at,
            }
            for agent, state in rows
        ]

    async def get_or_create_relationship(self, agent_a_id: UUID, agent_b_id: UUID) -> Tuple[TownRelationship, bool]:
        """Get or create a relationship between two agents."""
        a_id, b_id = sorted([agent_a_id, agent_b_id], key=str)

        result = await self.db.execute(
            select(TownRelationship).where(
                TownRelationship.agent_a_id == a_id,
                TownRelationship.agent_b_id == b_id,
            )
        )
        rel = result.scalar_one_or_none()

        if rel:
            return rel, False

        rel = TownRelationship(agent_a_id=a_id, agent_b_id=b_id)
        self.db.add(rel)
        await self.db.flush()
        return rel, True

    async def update_relationship(
        self,
        relationship_id: UUID,
        affinity_delta: int = 0,
        new_type: Optional[str] = None,
    ) -> TownRelationship:
        """Update relationship after an interaction."""
        result = await self.db.execute(select(TownRelationship).where(TownRelationship.id == relationship_id))
        rel = result.scalar_one()

        rel.affinity_score = max(-100, min(100, rel.affinity_score + affinity_delta))
        rel.interaction_count += 1
        rel.last_interaction_at = datetime.now(timezone.utc)
        if new_type:
            rel.relationship_type = new_type

        await self.db.flush()
        return rel

    async def store_conversation(
        self,
        participant_a_id: UUID,
        participant_b_id: UUID,
        location: str,
        public_log: list,
        topic_summary: Optional[str] = None,
    ) -> TownConversation:
        """Store a completed conversation."""
        convo = TownConversation(
            participant_a_id=participant_a_id,
            participant_b_id=participant_b_id,
            location=location,
            turn_count=len(public_log),
            topic_summary=topic_summary,
            public_log=public_log,
            ended_at=datetime.now(timezone.utc),
        )
        self.db.add(convo)
        await self.db.flush()
        return convo

    async def get_recent_conversations(self, limit: int = 20) -> List[TownConversation]:
        """Get recent town conversations."""
        result = await self.db.execute(
            select(TownConversation).order_by(TownConversation.started_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def get_recent_speech(self, since_seconds: float = 5.0) -> list[dict]:
        """Get chat messages from the last N seconds for speech bubbles."""
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=since_seconds)
        result = await self.db.execute(
            select(TownConversation)
            .where(TownConversation.updated_at >= cutoff)
            .order_by(TownConversation.updated_at.desc())
            .limit(10)
        )
        speeches = []
        for conv in result.scalars().all():
            if conv.public_log:
                last_msg = conv.public_log[-1]
                speeches.append(
                    {
                        "speaker": last_msg.get("speaker", "Unknown"),
                        "text": last_msg.get("text", "")[:100],
                        "conversation_id": str(conv.id),
                    }
                )
        return speeches

    async def seed_agent(
        self,
        user_id: str,
        agent_name: str,
        display_name: str,
        personality_summary: Optional[str] = None,
        position_x: float = 0.0,
        position_y: float = 0.0,
        home_location: str = "apartment",
    ) -> TownAgent:
        """Seed a default agent directly.

        Used by TownSimulation.seed_default_agents() for system-generated agents.
        If the agent already exists and is active, returns it unchanged.
        """
        existing = await self._get_town_agent(user_id, agent_name)
        if existing:
            if not existing.is_active:
                existing.is_active = True
                existing.last_active_at = datetime.now(timezone.utc)
            existing.display_name = display_name
            existing.personality_summary = personality_summary
            existing.home_location = home_location
            # Always update position on seed (supports map changes across deploys)
            state_result = await self.db.execute(select(TownState).where(TownState.agent_id == existing.id))
            state = state_result.scalar_one_or_none()
            if state:
                state.position_x = position_x
                state.position_y = position_y
                state.target_x = None
                state.target_y = None
                state.speed = 0.0
                state.current_activity = "idle"
                state.location_state = "active"
            await self.db.flush()
            return existing

        town_agent = TownAgent(
            user_id=user_id,
            agent_name=agent_name,
            display_name=display_name,
            personality_summary=personality_summary,
            home_location=home_location,
        )
        self.db.add(town_agent)
        await self.db.flush()

        state = TownState(
            agent_id=town_agent.id,
            position_x=position_x,
            position_y=position_y,
            current_location=home_location,
        )
        self.db.add(state)
        await self.db.flush()

        logger.info(f"Seeded default agent '{display_name}' at ({position_x}, {position_y})")
        return town_agent

    # ------------------------------------------------------------------
    # Instance-based opt-in / opt-out
    # ------------------------------------------------------------------

    async def get_instance_by_token(self, token: str) -> Optional[TownInstance]:
        """Look up an active instance by its town_token."""
        result = await self.db.execute(
            select(TownInstance).where(
                TownInstance.town_token == token,
                TownInstance.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def get_active_instance(self, user_id: str) -> Optional[TownInstance]:
        """Return the user's active TownInstance, or None."""
        result = await self.db.execute(
            select(TownInstance).where(
                TownInstance.user_id == user_id,
                TownInstance.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def create_instance(self, user_id: str) -> TownInstance:
        """Create a new TownInstance with unique apartment_unit and signed token."""
        max_unit = await self.db.execute(select(func.max(TownInstance.apartment_unit)))
        current_max = max_unit.scalar() or 0
        # Use a temporary random ID, then replace with signed token after flush
        temp_token = secrets.token_urlsafe(32)
        instance = TownInstance(
            user_id=user_id,
            apartment_unit=current_max + 1,
            town_token=temp_token,
        )
        self.db.add(instance)
        await self.db.flush()
        # Now sign with the real instance ID
        instance.town_token = sign_town_token(user_id, str(instance.id))
        await self.db.flush()
        return instance

    async def deactivate_instance(self, instance: TownInstance) -> None:
        """Deactivate a TownInstance."""
        instance.is_active = False
        await self.db.flush()

    async def get_instance_agents(self, instance_id: UUID) -> List[TownAgent]:
        """Return all active agents for a given instance."""
        result = await self.db.execute(
            select(TownAgent).where(
                TownAgent.instance_id == instance_id,
                TownAgent.is_active.is_(True),
            )
        )
        return list(result.scalars().all())

    async def deactivate_instance_agents(self, instance_id: UUID) -> int:
        """Deactivate all agents for an instance. Returns count."""
        agents = await self.get_instance_agents(instance_id)
        for agent in agents:
            agent.is_active = False
        await self.db.flush()
        return len(agents)

    async def opt_in_instance(
        self,
        user_id: str,
        agents_data: list,
    ) -> Tuple[TownInstance, List[TownAgent]]:
        """Instance-level opt-in: create instance + all agents + states."""
        existing = await self.get_active_instance(user_id)
        if existing:
            raise ValueError("User already has an active GooseTown instance")

        instance = await self.create_instance(user_id)
        created_agents = []

        from core.apartment_constants import APARTMENT_SPOTS

        bedroom = APARTMENT_SPOTS["bed_1"]

        for agent_data in agents_data:
            agent = TownAgent(
                user_id=user_id,
                agent_name=agent_data.agent_name,
                display_name=agent_data.display_name,
                personality_summary=agent_data.personality_summary,
                home_location="apartment",
                instance_id=instance.id,
            )
            self.db.add(agent)
            await self.db.flush()

            state = TownState(
                agent_id=agent.id,
                position_x=float(bedroom["x"]),
                position_y=float(bedroom["y"]),
                current_location="bedroom",
                location_state="active",
                location_context="apartment",
            )
            self.db.add(state)
            await self.db.flush()

            created_agents.append(agent)

        logger.info(
            f"Instance opt-in for user {user_id}: "
            f"apartment_unit={instance.apartment_unit}, agents={len(created_agents)}"
        )
        return instance, created_agents

    async def opt_out_instance(self, user_id: str) -> Tuple[Optional[TownInstance], int]:
        """Instance-level opt-out: deactivate instance + all agents."""
        instance = await self.get_active_instance(user_id)
        if not instance:
            return None, 0

        count = await self.deactivate_instance_agents(instance.id)
        await self.deactivate_instance(instance)

        logger.info(f"Instance opt-out for user {user_id}: deactivated {count} agents")
        return instance, count

    async def get_agent_by_name(self, user_id: str, agent_name: str) -> Optional[TownAgent]:
        """Look up an agent by user_id and agent_name (active only)."""
        result = await self.db.execute(
            select(TownAgent).where(
                TownAgent.user_id == user_id,
                TownAgent.agent_name == agent_name,
                TownAgent.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def _get_town_agent(self, user_id: str, agent_name: str) -> Optional[TownAgent]:
        """Get a town agent by user_id and agent_name."""
        result = await self.db.execute(
            select(TownAgent).where(
                TownAgent.user_id == user_id,
                TownAgent.agent_name == agent_name,
            )
        )
        return result.scalar_one_or_none()

    async def get_town_agent_by_id(self, agent_id: UUID) -> Optional[TownAgent]:
        """Get a town agent by its UUID."""
        result = await self.db.execute(select(TownAgent).where(TownAgent.id == agent_id))
        return result.scalar_one_or_none()

    async def update_agent_state(
        self,
        agent_id: UUID,
        **kwargs,
    ) -> Optional[TownState]:
        """Update an agent's town state."""
        result = await self.db.execute(select(TownState).where(TownState.agent_id == agent_id))
        state = result.scalar_one_or_none()
        if not state:
            return None

        for key, value in kwargs.items():
            if hasattr(state, key):
                setattr(state, key, value)

        await self.db.flush()
        return state
