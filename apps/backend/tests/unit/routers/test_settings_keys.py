"""Tests for BYOK API key management."""

from unittest.mock import patch

import pytest
from sqlalchemy import select

from models.user_api_key import UserApiKey

# Deterministic test encryption key (base64url-encoded 32 bytes, Fernet-compatible)
_TEST_ENCRYPTION_KEY = "dGVzdC1lbmNyeXB0aW9uLWtleS0xMjM0NTY3OA=="


@pytest.fixture(autouse=True)
def _set_encryption_key():
    """Ensure ENCRYPTION_KEY is set for all tests in this module."""
    with patch("core.config.settings.ENCRYPTION_KEY", _TEST_ENCRYPTION_KEY):
        yield


class TestSettingsKeys:
    @pytest.mark.asyncio
    async def test_list_keys_empty(self, async_client):
        """GET /settings/keys returns empty list initially."""
        resp = await async_client.get("/api/v1/settings/keys")
        assert resp.status_code == 200
        data = resp.json()
        assert data["keys"] == []
        assert "supported_tools" in data

    @pytest.mark.asyncio
    async def test_set_key(self, async_client, db_session):
        """PUT /settings/keys/{tool_id} stores a key."""
        resp = await async_client.put(
            "/api/v1/settings/keys/elevenlabs",
            json={"api_key": "sk-test-key-123"},
        )
        assert resp.status_code == 200
        assert resp.json()["tool_id"] == "elevenlabs"

        # Verify in DB
        result = await db_session.execute(select(UserApiKey).where(UserApiKey.user_id == "user_test_123"))
        key = result.scalar_one()
        assert key.tool_id == "elevenlabs"
        # Key must be encrypted — NOT stored as plaintext
        assert key.encrypted_key != "sk-test-key-123"
        assert len(key.encrypted_key) > 0

    @pytest.mark.asyncio
    async def test_set_key_unsupported_tool(self, async_client):
        """PUT /settings/keys/{tool_id} rejects unsupported tools."""
        resp = await async_client.put(
            "/api/v1/settings/keys/unknown_tool",
            json={"api_key": "sk-test"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_delete_key(self, async_client, db_session):
        """DELETE /settings/keys/{tool_id} removes the key."""
        # First set a key
        key = UserApiKey(
            user_id="user_test_123",
            tool_id="elevenlabs",
            encrypted_key="sk-to-delete",
        )
        db_session.add(key)
        await db_session.commit()

        resp = await async_client.delete("/api/v1/settings/keys/elevenlabs")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_delete_key_not_found(self, async_client):
        """DELETE /settings/keys/{tool_id} returns 404 when no key exists."""
        resp = await async_client.delete("/api/v1/settings/keys/elevenlabs")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_list_keys_shows_configured(self, async_client, db_session):
        """GET /settings/keys shows configured tools without values."""
        key = UserApiKey(
            user_id="user_test_123",
            tool_id="elevenlabs",
            encrypted_key="sk-secret",
        )
        db_session.add(key)
        await db_session.commit()

        resp = await async_client.get("/api/v1/settings/keys")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["keys"]) == 1
        assert data["keys"][0]["tool_id"] == "elevenlabs"
        # Must NOT expose the actual key value
        assert "sk-secret" not in str(data)
