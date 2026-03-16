"""Tests for UserApiKey model."""

import uuid

import pytest
from sqlalchemy import select

from models.user_api_key import UserApiKey


class TestUserApiKey:
    @pytest.mark.asyncio
    async def test_user_api_key_creation(self, db_session):
        key = UserApiKey(
            id=uuid.uuid4(),
            user_id="user_clerk_123",
            tool_id="elevenlabs",
            encrypted_key="encrypted_data_here",
        )
        db_session.add(key)
        await db_session.commit()

        result = await db_session.execute(select(UserApiKey).where(UserApiKey.user_id == "user_clerk_123"))
        saved = result.scalar_one()
        assert saved.user_id == "user_clerk_123"
        assert saved.tool_id == "elevenlabs"
        assert saved.encrypted_key == "encrypted_data_here"
        assert repr(saved) == "<UserApiKey(user=user_clerk_123, tool=elevenlabs)>"

    @pytest.mark.asyncio
    async def test_user_api_key_timestamps(self, db_session):
        key = UserApiKey(
            id=uuid.uuid4(),
            user_id="user_1",
            tool_id="openai_tts",
            encrypted_key="enc",
        )
        db_session.add(key)
        await db_session.commit()
        assert key.created_at is not None
        assert key.updated_at is not None

    @pytest.mark.asyncio
    async def test_user_api_key_unique_constraint(self, db_session):
        """Cannot have two keys for the same user+tool combination."""
        key1 = UserApiKey(
            id=uuid.uuid4(),
            user_id="user_dup",
            tool_id="elevenlabs",
            encrypted_key="key1",
        )
        db_session.add(key1)
        await db_session.commit()

        key2 = UserApiKey(
            id=uuid.uuid4(),
            user_id="user_dup",
            tool_id="elevenlabs",
            encrypted_key="key2",
        )
        db_session.add(key2)
        with pytest.raises(Exception):
            await db_session.commit()
