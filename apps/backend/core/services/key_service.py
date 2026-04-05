"""Service for managing user-provided API keys (BYOK)."""

import logging
from typing import Optional

from core.encryption import decrypt, encrypt
from core.repositories import api_key_repo

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

    async def set_key(self, user_id: str, tool_id: str, api_key: str) -> dict:
        if tool_id not in SUPPORTED_TOOLS:
            raise ValueError(f"Unsupported tool: {tool_id}")

        encrypted = encrypt(api_key)
        item = await api_key_repo.set_key(
            user_id=user_id,
            tool_id=tool_id,
            encrypted_key=encrypted,
        )
        return item

    async def delete_key(self, user_id: str, tool_id: str) -> bool:
        return await api_key_repo.delete_key(user_id, tool_id)

    async def list_keys(self, user_id: str) -> list[dict]:
        items = await api_key_repo.list_keys(user_id)
        return [
            {
                "tool_id": item["tool_id"],
                "display_name": SUPPORTED_TOOLS.get(item["tool_id"], {}).get("display_name", item["tool_id"]),
                "created_at": item.get("created_at"),
            }
            for item in items
        ]

    async def get_key(self, user_id: str, tool_id: str) -> Optional[str]:
        item = await api_key_repo.get_key(user_id, tool_id)
        return decrypt(item["encrypted_key"]) if item else None
