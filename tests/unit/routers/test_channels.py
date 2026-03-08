"""Tests for channel management router."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestChannelRouter:
    @pytest.fixture
    def mock_container(self):
        """A mock container with gateway_token."""
        container = MagicMock()
        container.gateway_token = "test-gw-token"
        return container

    @pytest.fixture
    def channel_mocks(self, mock_container):
        """Patch all dependencies for _send_channel_rpc."""
        mock_pool = AsyncMock()
        mock_pool.send_rpc = AsyncMock(return_value={"ok": True})

        mock_ecs = AsyncMock()
        mock_ecs.resolve_running_container = AsyncMock(return_value=(mock_container, "10.0.1.5"))

        mock_session_factory = MagicMock()
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session_factory.return_value = mock_session

        with (
            patch("routers.channels.get_gateway_pool", return_value=mock_pool),
            patch("routers.channels.get_ecs_manager", return_value=mock_ecs),
            patch("routers.channels.get_session_factory", return_value=mock_session_factory),
        ):
            yield mock_pool

    @pytest.mark.asyncio
    async def test_list_channels(self, async_client, channel_mocks):
        """GET /channels returns channel status from RPC."""
        mock_pool = channel_mocks
        mock_pool.send_rpc = AsyncMock(
            return_value=[
                {"provider": "telegram", "status": "connected"},
            ]
        )

        resp = await async_client.get("/api/v1/channels")
        assert resp.status_code == 200
        data = resp.json()
        assert "channels" in data

    @pytest.mark.asyncio
    @patch("routers.channels.get_gateway_pool")
    @patch("routers.channels.get_ecs_manager")
    async def test_list_channels_handles_rpc_failure(self, mock_ecs_fn, mock_pool_fn, async_client):
        """GET /channels returns empty list on RPC failure."""
        mock_ecs = AsyncMock()
        mock_ecs.resolve_running_container = AsyncMock(side_effect=Exception("Container unreachable"))
        mock_ecs_fn.return_value = mock_ecs

        mock_pool = AsyncMock()
        mock_pool_fn.return_value = mock_pool

        with patch("routers.channels.get_session_factory") as mock_sf:
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_sf.return_value = MagicMock(return_value=mock_session)

            resp = await async_client.get("/api/v1/channels")
        assert resp.status_code == 200
        assert resp.json()["channels"] == []

    @pytest.mark.asyncio
    async def test_configure_telegram(self, async_client, channel_mocks):
        """POST /channels/telegram sends configure RPC."""
        mock_pool = channel_mocks

        resp = await async_client.post(
            "/api/v1/channels/telegram",
            json={"bot_token": "123456:ABC-DEF"},
        )
        assert resp.status_code == 200
        assert resp.json()["provider"] == "telegram"
        mock_pool.send_rpc.assert_called_once()
        call_args = mock_pool.send_rpc.call_args
        assert call_args[0][0] == "user_test_123"  # user_id
        assert call_args[0][2] == "channels.configure"  # method
        assert call_args[0][3] == {"provider": "telegram", "token": "123456:ABC-DEF"}  # params

    @pytest.mark.asyncio
    async def test_configure_discord(self, async_client, channel_mocks):
        """POST /channels/discord sends configure RPC."""
        resp = await async_client.post(
            "/api/v1/channels/discord",
            json={"bot_token": "discord_token", "guild_id": "guild_123"},
        )
        assert resp.status_code == 200
        assert resp.json()["provider"] == "discord"

    @pytest.mark.asyncio
    async def test_whatsapp_pair(self, async_client, channel_mocks):
        """POST /channels/whatsapp/pair initiates QR pairing."""
        mock_pool = channel_mocks
        mock_pool.send_rpc = AsyncMock(return_value={"qr": "data:image/png;base64,..."})

        resp = await async_client.post("/api/v1/channels/whatsapp/pair")
        assert resp.status_code == 200
        assert resp.json()["status"] == "pairing"
        assert "qr" in resp.json()

    @pytest.mark.asyncio
    async def test_whatsapp_qr_poll(self, async_client, channel_mocks):
        """GET /channels/whatsapp/qr returns current QR code."""
        mock_pool = channel_mocks
        mock_pool.send_rpc = AsyncMock(return_value={"qr": "base64data", "expires": 30})

        resp = await async_client.get("/api/v1/channels/whatsapp/qr")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_disconnect_channel(self, async_client, channel_mocks):
        """DELETE /channels/{provider} sends disconnect RPC."""
        resp = await async_client.delete("/api/v1/channels/telegram")
        assert resp.status_code == 200
        assert resp.json()["provider"] == "telegram"

    @pytest.mark.asyncio
    async def test_disconnect_unknown_provider(self, async_client):
        """DELETE /channels/{provider} rejects unknown providers."""
        resp = await async_client.delete("/api/v1/channels/unknown")
        assert resp.status_code == 400
