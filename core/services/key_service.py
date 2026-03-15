"""Service for managing user-provided API keys (BYOK).

Keys are encrypted at rest using AWS KMS when KMS_API_KEY_ID is configured.
Without KMS (local dev / unset), keys are stored as plaintext with a warning.
"""

import base64
import logging
from typing import Optional

import boto3
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
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

_kms_client = None


def _get_kms_client():
    """Return a lazy-initialized KMS boto3 client, or None if not configured."""
    global _kms_client
    if not settings.KMS_API_KEY_ID:
        return None
    if _kms_client is None:
        _kms_client = boto3.client("kms", region_name=settings.AWS_REGION)
    return _kms_client


def _encrypt(plaintext: str) -> str:
    """Encrypt a plaintext API key with KMS.

    Returns the KMS ciphertext as a base64 string for DB storage.
    Falls back to plaintext (with a warning) if KMS is not configured.
    """
    kms = _get_kms_client()
    if kms is None:
        logger.warning(
            "KMS_API_KEY_ID not set — storing API key in plaintext. "
            "Set KMS_API_KEY_ID in production."
        )
        return plaintext

    response = kms.encrypt(
        KeyId=settings.KMS_API_KEY_ID,
        Plaintext=plaintext.encode("utf-8"),
    )
    return base64.b64encode(response["CiphertextBlob"]).decode("utf-8")


def _decrypt(stored_value: str) -> str:
    """Decrypt a KMS-encrypted API key.

    Accepts the base64-encoded ciphertext written by _encrypt().
    Falls back to returning the value as-is if KMS is not configured
    (matches the plaintext fallback in _encrypt).
    """
    kms = _get_kms_client()
    if kms is None:
        return stored_value

    ciphertext = base64.b64decode(stored_value.encode("utf-8"))
    response = kms.decrypt(
        KeyId=settings.KMS_API_KEY_ID,
        CiphertextBlob=ciphertext,
    )
    return response["Plaintext"].decode("utf-8")


class KeyService:
    """Manages user-provided API keys."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def set_key(self, user_id: str, tool_id: str, api_key: str) -> UserApiKey:
        if tool_id not in SUPPORTED_TOOLS:
            raise ValueError(f"Unsupported tool: {tool_id}")

        encrypted = _encrypt(api_key)

        result = await self.db.execute(
            select(UserApiKey).where(
                UserApiKey.user_id == user_id,
                UserApiKey.tool_id == tool_id,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.encrypted_key = encrypted
            await self.db.flush()
            return existing

        key = UserApiKey(
            user_id=user_id,
            tool_id=tool_id,
            encrypted_key=encrypted,
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
        if key is None:
            return None
        return _decrypt(key.encrypted_key)
