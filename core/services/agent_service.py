"""
Agent service for managing agent metadata.

Agent state lives as plain files on disk. The database stores
metadata only (name, soul content, timestamps).
"""

import logging
from typing import List, Optional

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent_state import AgentState

logger = logging.getLogger(__name__)


class AgentService:
    """Service for managing agent metadata in the database."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_agent(self, user_id: str, agent_name: str) -> Optional[AgentState]:
        """Get agent by user_id and agent_name."""
        result = await self.db.execute(
            select(AgentState).where(
                AgentState.user_id == user_id,
                AgentState.agent_name == agent_name,
            )
        )
        return result.scalar_one_or_none()

    async def create_agent(
        self,
        user_id: str,
        agent_name: str,
        soul_content: Optional[str] = None,
    ) -> AgentState:
        """Create a new agent."""
        state = AgentState(
            user_id=user_id,
            agent_name=agent_name,
            soul_content=soul_content,
        )
        self.db.add(state)
        await self.db.flush()
        logger.info("Created agent for user=%s, agent=%s", user_id, agent_name)
        return state

    async def list_agents(self, user_id: str) -> List[AgentState]:
        """List all agents for a user."""
        result = await self.db.execute(
            select(AgentState)
            .where(AgentState.user_id == user_id)
            .order_by(AgentState.created_at.desc())
        )
        return list(result.scalars().all())

    async def delete_agent(self, user_id: str, agent_name: str) -> bool:
        """Delete an agent. Returns True if deleted, False if not found."""
        result = await self.db.execute(
            delete(AgentState).where(
                AgentState.user_id == user_id,
                AgentState.agent_name == agent_name,
            )
        )
        deleted = result.rowcount > 0
        if deleted:
            await self.db.flush()
            logger.info("Deleted agent for user=%s, agent=%s", user_id, agent_name)
        return deleted

    async def update_soul_content(
        self, user_id: str, agent_name: str, soul_content: str
    ) -> Optional[AgentState]:
        """Update an agent's soul content."""
        agent = await self.get_agent(user_id, agent_name)
        if agent is None:
            return None
        agent.soul_content = soul_content
        await self.db.flush()
        return agent
