"""Service for managing user-provided API keys (BYOK)."""

import logging
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.user_api_key import UserApiKey

logger = logging.getLogger(__name__)

SUPPORTED_TOOLS = {
    "elevenlabs": {
        "display_name": "ElevenLabs TTS",
        "config_path": "tts.elevenlabs.apiKey",
    },
    "openai_tts": {
        "display_name": "OpenAI TTS",
        "config_path": "tts.openai.apiKey",
    },
    "perplexity": {
        "display_name": "Perplexity Search",
        "config_path": "tools.web.search.perplexity.apiKey",
    },
    "firecrawl": {
        "display_name": "Firecrawl",
        "config_path": "tools.web.fetch.firecrawl.apiKey",
    },
}


class KeyService:
    """Manages user-provided API keys."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def set_key(self, user_id: str, tool_id: str, api_key: str) -> UserApiKey:
        if tool_id not in SUPPORTED_TOOLS:
            raise ValueError(f"Unsupported tool: {tool_id}")

        result = await self.db.execute(
            select(UserApiKey).where(
                UserApiKey.user_id == user_id,
                UserApiKey.tool_id == tool_id,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.encrypted_key = api_key  # TODO: encrypt with KMS
            await self.db.flush()
            return existing

        key = UserApiKey(
            user_id=user_id,
            tool_id=tool_id,
            encrypted_key=api_key,  # TODO: encrypt with KMS
        )
        self.db.add(key)
        await self.db.flush()
        return key

    async def delete_key(self, user_id: str, tool_id: str) -> bool:
        result = await self.db.execute(
            delete(UserApiKey).where(
                UserApiKey.user_id == user_id,
                UserApiKey.tool_id == tool_id,
            )
        )
        return result.rowcount > 0

    async def list_keys(self, user_id: str) -> list[dict]:
        result = await self.db.execute(
            select(UserApiKey.tool_id, UserApiKey.created_at).where(
                UserApiKey.user_id == user_id,
            )
        )
        return [
            {
                "tool_id": row.tool_id,
                "display_name": SUPPORTED_TOOLS.get(row.tool_id, {}).get("display_name", row.tool_id),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in result.all()
        ]

    async def get_key(self, user_id: str, tool_id: str) -> Optional[str]:
        result = await self.db.execute(
            select(UserApiKey).where(
                UserApiKey.user_id == user_id,
                UserApiKey.tool_id == tool_id,
            )
        )
        key = result.scalar_one_or_none()
        return key.encrypted_key if key else None  # TODO: decrypt with KMS
