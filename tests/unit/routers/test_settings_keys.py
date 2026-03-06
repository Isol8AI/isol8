"""Tests for BYOK API key management."""

import pytest
from unittest.mock import patch
from sqlalchemy import select

from models.user_api_key import UserApiKey


class TestSettingsKeys:
    @pytest.mark.asyncio
    async def test_list_keys_empty(self, async_client, override_get_session_factory):
        """GET /settings/keys returns empty list initially."""
        with patch("routers.settings_keys.get_session_factory", override_get_session_factory):
            resp = await async_client.get("/api/v1/settings/keys")
        assert resp.status_code == 200
        data = resp.json()
        assert data["keys"] == []
        assert "supported_tools" in data

    @pytest.mark.asyncio
    async def test_set_key(self, async_client, db_session, override_get_session_factory):
        """PUT /settings/keys/{tool_id} stores a key."""
        with patch("routers.settings_keys.get_session_factory", override_get_session_factory):
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
        assert key.encrypted_key == "sk-test-key-123"

    @pytest.mark.asyncio
    async def test_set_key_unsupported_tool(self, async_client, override_get_session_factory):
        """PUT /settings/keys/{tool_id} rejects unsupported tools."""
        with patch("routers.settings_keys.get_session_factory", override_get_session_factory):
            resp = await async_client.put(
                "/api/v1/settings/keys/unknown_tool",
                json={"api_key": "sk-test"},
            )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_delete_key(self, async_client, db_session, override_get_session_factory):
        """DELETE /settings/keys/{tool_id} removes the key."""
        # First set a key
        key = UserApiKey(
            user_id="user_test_123",
            tool_id="elevenlabs",
            encrypted_key="sk-to-delete",
        )
        db_session.add(key)
        await db_session.commit()

        with patch("routers.settings_keys.get_session_factory", override_get_session_factory):
            resp = await async_client.delete("/api/v1/settings/keys/elevenlabs")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_delete_key_not_found(self, async_client, override_get_session_factory):
        """DELETE /settings/keys/{tool_id} returns 404 when no key exists."""
        with patch("routers.settings_keys.get_session_factory", override_get_session_factory):
            resp = await async_client.delete("/api/v1/settings/keys/elevenlabs")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_list_keys_shows_configured(self, async_client, db_session, override_get_session_factory):
        """GET /settings/keys shows configured tools without values."""
        key = UserApiKey(
            user_id="user_test_123",
            tool_id="elevenlabs",
            encrypted_key="sk-secret",
        )
        db_session.add(key)
        await db_session.commit()

        with patch("routers.settings_keys.get_session_factory", override_get_session_factory):
            resp = await async_client.get("/api/v1/settings/keys")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["keys"]) == 1
        assert data["keys"][0]["tool_id"] == "elevenlabs"
        # Must NOT expose the actual key value
        assert "sk-secret" not in str(data)
