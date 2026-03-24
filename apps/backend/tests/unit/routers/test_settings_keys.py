"""Tests for BYOK API key management."""

from unittest.mock import patch, AsyncMock

import pytest
from cryptography.fernet import Fernet

# Deterministic test encryption key (Fernet-compatible)
_TEST_ENCRYPTION_KEY = Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def _set_encryption_key():
    """Ensure ENCRYPTION_KEY is set for all tests in this module."""
    with patch("core.config.settings.ENCRYPTION_KEY", _TEST_ENCRYPTION_KEY):
        yield


class TestSettingsKeys:
    @pytest.mark.asyncio
    @patch("routers.settings_keys.key_service")
    async def test_list_keys_empty(self, mock_svc, async_client):
        """GET /settings/keys returns empty list initially."""
        mock_svc.list_keys = AsyncMock(return_value=[])
        resp = await async_client.get("/api/v1/settings/keys")
        assert resp.status_code == 200
        data = resp.json()
        assert data["keys"] == []
        assert "supported_tools" in data

    @pytest.mark.asyncio
    @patch("routers.settings_keys.key_service")
    async def test_set_key(self, mock_svc, async_client):
        """PUT /settings/keys/{tool_id} stores a key."""
        mock_svc.set_key = AsyncMock(return_value={"user_id": "user_test_123", "tool_id": "elevenlabs"})
        resp = await async_client.put(
            "/api/v1/settings/keys/elevenlabs",
            json={"api_key": "sk-test-key-123"},
        )
        assert resp.status_code == 200
        assert resp.json()["tool_id"] == "elevenlabs"

    @pytest.mark.asyncio
    @patch("routers.settings_keys.key_service")
    async def test_set_key_unsupported_tool(self, mock_svc, async_client):
        """PUT /settings/keys/{tool_id} rejects unsupported tools."""
        mock_svc.set_key = AsyncMock(side_effect=ValueError("Unsupported tool"))
        resp = await async_client.put(
            "/api/v1/settings/keys/unknown_tool",
            json={"api_key": "sk-test"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    @patch("routers.settings_keys.key_service")
    async def test_delete_key(self, mock_svc, async_client):
        """DELETE /settings/keys/{tool_id} removes the key."""
        mock_svc.delete_key = AsyncMock(return_value=True)
        resp = await async_client.delete("/api/v1/settings/keys/elevenlabs")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    @patch("routers.settings_keys.key_service")
    async def test_delete_key_not_found(self, mock_svc, async_client):
        """DELETE /settings/keys/{tool_id} returns 404 when no key exists."""
        mock_svc.delete_key = AsyncMock(return_value=False)
        resp = await async_client.delete("/api/v1/settings/keys/elevenlabs")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    @patch("routers.settings_keys.key_service")
    async def test_list_keys_shows_configured(self, mock_svc, async_client):
        """GET /settings/keys shows configured tools without values."""
        mock_svc.list_keys = AsyncMock(
            return_value=[{"tool_id": "elevenlabs", "display_name": "ElevenLabs", "created_at": "2026-01-01T00:00:00Z"}]
        )
        resp = await async_client.get("/api/v1/settings/keys")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["keys"]) == 1
        assert data["keys"][0]["tool_id"] == "elevenlabs"
