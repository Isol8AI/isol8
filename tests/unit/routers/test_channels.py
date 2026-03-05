"""Tests for channel management router."""

from unittest.mock import AsyncMock, patch

import pytest


class TestChannelRouter:
    @pytest.mark.asyncio
    @patch("routers.channels.get_gateway_pool")
    async def test_list_channels(self, mock_pool_fn, async_client):
        """GET /channels returns channel status from RPC."""
        mock_pool = AsyncMock()
        mock_pool.send_rpc = AsyncMock(
            return_value=[
                {"provider": "telegram", "status": "connected"},
            ]
        )
        mock_pool_fn.return_value = mock_pool

        resp = await async_client.get("/api/v1/channels")
        assert resp.status_code == 200
        data = resp.json()
        assert "channels" in data

    @pytest.mark.asyncio
    @patch("routers.channels.get_gateway_pool")
    async def test_list_channels_handles_rpc_failure(self, mock_pool_fn, async_client):
        """GET /channels returns empty list on RPC failure."""
        mock_pool = AsyncMock()
        mock_pool.send_rpc = AsyncMock(side_effect=Exception("Container unreachable"))
        mock_pool_fn.return_value = mock_pool

        resp = await async_client.get("/api/v1/channels")
        assert resp.status_code == 200
        assert resp.json()["channels"] == []

    @pytest.mark.asyncio
    @patch("routers.channels.get_gateway_pool")
    async def test_configure_telegram(self, mock_pool_fn, async_client):
        """POST /channels/telegram sends configure RPC."""
        mock_pool = AsyncMock()
        mock_pool.send_rpc = AsyncMock(return_value={"ok": True})
        mock_pool_fn.return_value = mock_pool

        resp = await async_client.post(
            "/api/v1/channels/telegram",
            json={"bot_token": "123456:ABC-DEF"},
        )
        assert resp.status_code == 200
        assert resp.json()["provider"] == "telegram"
        mock_pool.send_rpc.assert_called_once_with(
            "user_test_123",
            "channels.configure",
            {"provider": "telegram", "token": "123456:ABC-DEF"},
        )

    @pytest.mark.asyncio
    @patch("routers.channels.get_gateway_pool")
    async def test_configure_discord(self, mock_pool_fn, async_client):
        """POST /channels/discord sends configure RPC."""
        mock_pool = AsyncMock()
        mock_pool.send_rpc = AsyncMock(return_value={"ok": True})
        mock_pool_fn.return_value = mock_pool

        resp = await async_client.post(
            "/api/v1/channels/discord",
            json={"bot_token": "discord_token", "guild_id": "guild_123"},
        )
        assert resp.status_code == 200
        assert resp.json()["provider"] == "discord"

    @pytest.mark.asyncio
    @patch("routers.channels.get_gateway_pool")
    async def test_whatsapp_pair(self, mock_pool_fn, async_client):
        """POST /channels/whatsapp/pair initiates QR pairing."""
        mock_pool = AsyncMock()
        mock_pool.send_rpc = AsyncMock(return_value={"qr": "data:image/png;base64,..."})
        mock_pool_fn.return_value = mock_pool

        resp = await async_client.post("/api/v1/channels/whatsapp/pair")
        assert resp.status_code == 200
        assert resp.json()["status"] == "pairing"
        assert "qr" in resp.json()

    @pytest.mark.asyncio
    @patch("routers.channels.get_gateway_pool")
    async def test_whatsapp_qr_poll(self, mock_pool_fn, async_client):
        """GET /channels/whatsapp/qr returns current QR code."""
        mock_pool = AsyncMock()
        mock_pool.send_rpc = AsyncMock(return_value={"qr": "base64data", "expires": 30})
        mock_pool_fn.return_value = mock_pool

        resp = await async_client.get("/api/v1/channels/whatsapp/qr")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    @patch("routers.channels.get_gateway_pool")
    async def test_disconnect_channel(self, mock_pool_fn, async_client):
        """DELETE /channels/{provider} sends disconnect RPC."""
        mock_pool = AsyncMock()
        mock_pool.send_rpc = AsyncMock(return_value={"ok": True})
        mock_pool_fn.return_value = mock_pool

        resp = await async_client.delete("/api/v1/channels/telegram")
        assert resp.status_code == 200
        assert resp.json()["provider"] == "telegram"

    @pytest.mark.asyncio
    async def test_disconnect_unknown_provider(self, async_client):
        """DELETE /channels/{provider} rejects unknown providers."""
        resp = await async_client.delete("/api/v1/channels/unknown")
        assert resp.status_code == 400
