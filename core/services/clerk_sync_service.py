"""
Clerk Sync Service - syncs Clerk user data to our database.

Simplified: personal agents only, no organizations.
"""

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User

logger = logging.getLogger(__name__)


class ClerkSyncService:
    """Service for syncing Clerk data to our database."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_user(self, data: dict) -> User:
        """Create user from Clerk webhook data."""
        user_id = data.get("id")

        result = await self.db.execute(select(User).where(User.id == user_id))
        existing = result.scalar_one_or_none()
        if existing:
            logger.info("User %s already exists", user_id)
            return existing

        user = User(id=user_id)
        self.db.add(user)
        await self.db.commit()

        logger.info("Created user %s", user_id)
        return user

    async def update_user(self, data: dict) -> Optional[User]:
        """Update user from Clerk webhook data."""
        user_id = data.get("id")

        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

        if not user:
            logger.warning("User %s not found for update, creating", user_id)
            return await self.create_user(data)

        await self.db.commit()
        logger.info("Updated user %s", user_id)
        return user

    async def delete_user(self, data: dict) -> None:
        """Delete user."""
        user_id = data.get("id")

        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

        if not user:
            logger.warning("User %s not found for deletion", user_id)
            return

        await self.db.delete(user)
        await self.db.commit()
        logger.warning("Deleted user %s", user_id)
