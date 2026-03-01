"""Tests for the container RPC proxy endpoint."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestContainerRpcEndpoint:
    @pytest.mark.asyncio
    @patch("routers.container_rpc.get_container_manager")
    async def test_rpc_returns_404_when_no_container(self, mock_get_cm, async_client, test_user):
        mock_cm = MagicMock()
        mock_cm.get_container_info.return_value = None
        mock_get_cm.return_value = mock_cm

        response = await async_client.post(
            "/api/v1/container/rpc",
            json={"method": "health"},
        )
        assert response.status_code == 404
        assert "container" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    @patch("routers.container_rpc.get_container_manager")
    async def test_rpc_returns_404_when_container_stopped(self, mock_get_cm, async_client, test_user):
        info = MagicMock()
        info.status = "stopped"
        mock_cm = MagicMock()
        mock_cm.get_container_info.return_value = info
        mock_get_cm.return_value = mock_cm

        response = await async_client.post(
            "/api/v1/container/rpc",
            json={"method": "health"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_rpc_requires_method(self, async_client, test_user):
        response = await async_client.post(
            "/api/v1/container/rpc",
            json={},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_rpc_requires_auth(self, unauthenticated_async_client):
        response = await unauthenticated_async_client.post(
            "/api/v1/container/rpc",
            json={"method": "health"},
        )
        assert response.status_code in (401, 403)

    @pytest.mark.asyncio
    @patch("routers.container_rpc._call_gateway_rpc")
    @patch("routers.container_rpc.get_container_manager")
    async def test_rpc_forwards_and_returns_result(self, mock_get_cm, mock_call_rpc, async_client, test_user):
        info = MagicMock()
        info.status = "running"
        info.port = 19001
        info.gateway_token = "test-token"
        mock_cm = MagicMock()
        mock_cm.get_container_info.return_value = info
        mock_get_cm.return_value = mock_cm

        mock_call_rpc.return_value = {"status": "ok", "uptime": 3600}

        response = await async_client.post(
            "/api/v1/container/rpc",
            json={"method": "health"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["result"]["status"] == "ok"
        assert data["result"]["uptime"] == 3600
        mock_call_rpc.assert_called_once_with(port=19001, token="test-token", method="health", params=None)

    @pytest.mark.asyncio
    @patch("routers.container_rpc._call_gateway_rpc")
    @patch("routers.container_rpc.get_container_manager")
    async def test_rpc_passes_params(self, mock_get_cm, mock_call_rpc, async_client, test_user):
        info = MagicMock()
        info.status = "running"
        info.port = 19001
        info.gateway_token = "t"
        mock_cm = MagicMock()
        mock_cm.get_container_info.return_value = info
        mock_get_cm.return_value = mock_cm

        mock_call_rpc.return_value = []

        response = await async_client.post(
            "/api/v1/container/rpc",
            json={"method": "sessions.list", "params": {"limit": 10}},
        )
        assert response.status_code == 200
        mock_call_rpc.assert_called_once_with(port=19001, token="t", method="sessions.list", params={"limit": 10})

    @pytest.mark.asyncio
    @patch("routers.container_rpc._call_gateway_rpc")
    @patch("routers.container_rpc.get_container_manager")
    async def test_rpc_returns_502_on_connection_refused(self, mock_get_cm, mock_call_rpc, async_client, test_user):
        info = MagicMock()
        info.status = "running"
        info.port = 19001
        info.gateway_token = "t"
        mock_cm = MagicMock()
        mock_cm.get_container_info.return_value = info
        mock_get_cm.return_value = mock_cm

        mock_call_rpc.side_effect = ConnectionRefusedError("refused")

        response = await async_client.post(
            "/api/v1/container/rpc",
            json={"method": "health"},
        )
        assert response.status_code == 502
        assert "not responding" in response.json()["detail"]

    @pytest.mark.asyncio
    @patch("routers.container_rpc._call_gateway_rpc")
    @patch("routers.container_rpc.get_container_manager")
    async def test_rpc_returns_502_on_timeout(self, mock_get_cm, mock_call_rpc, async_client, test_user):
        info = MagicMock()
        info.status = "running"
        info.port = 19001
        info.gateway_token = "t"
        mock_cm = MagicMock()
        mock_cm.get_container_info.return_value = info
        mock_get_cm.return_value = mock_cm

        mock_call_rpc.side_effect = TimeoutError("timed out")

        response = await async_client.post(
            "/api/v1/container/rpc",
            json={"method": "health"},
        )
        assert response.status_code == 502
        assert "timed out" in response.json()["detail"]


class TestCallGatewayRpc:
    """Unit tests for the _call_gateway_rpc function."""

    RPC_ID = "test-rpc-id"

    def _make_handshake_ws(self, rpc_payload: dict, extra_events: list | None = None) -> AsyncMock:
        """Create a mock WS that completes the connect handshake then returns rpc_payload.

        Args:
            rpc_payload: The payload field of the RPC response.
            extra_events: Optional list of event messages received before the RPC response.
        """
        mock_ws = AsyncMock()
        messages = [
            json.dumps({"event": "connect.challenge"}),
            json.dumps({"ok": True}),
        ]
        if extra_events:
            messages.extend(json.dumps(e) for e in extra_events)
        messages.append(
            json.dumps(
                {
                    "type": "res",
                    "id": self.RPC_ID,
                    "ok": True,
                    "payload": rpc_payload,
                }
            )
        )
        mock_ws.recv = AsyncMock(side_effect=messages)
        return mock_ws

    @pytest.mark.asyncio
    @patch("routers.container_rpc.uuid.uuid4")
    async def test_sends_method_and_params(self, mock_uuid):
        from routers.container_rpc import _call_gateway_rpc

        # First uuid call is handshake, second is our RPC request id
        mock_uuid.side_effect = ["handshake-id", self.RPC_ID]
        mock_ws = self._make_handshake_ws({"agents": ["main"]})

        with patch("routers.container_rpc.ws_connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_ws)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _call_gateway_rpc(port=19001, token="tok", method="agents.list", params={"active": True})

        assert result == {"agents": ["main"]}
        # Second send call is the RPC request (first is the connect handshake)
        rpc_sent = json.loads(mock_ws.send.call_args_list[1][0][0])
        assert rpc_sent["method"] == "agents.list"
        assert rpc_sent["params"] == {"active": True}

    @pytest.mark.asyncio
    @patch("routers.container_rpc.uuid.uuid4")
    async def test_sets_auth_in_handshake(self, mock_uuid):
        from routers.container_rpc import _call_gateway_rpc

        mock_uuid.side_effect = ["handshake-id", self.RPC_ID]
        mock_ws = self._make_handshake_ws({})

        with patch("routers.container_rpc.ws_connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_ws)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=False)

            await _call_gateway_rpc(port=19001, token="my-secret", method="health")

        # First send call is the connect handshake with auth token
        connect_sent = json.loads(mock_ws.send.call_args_list[0][0][0])
        assert connect_sent["method"] == "connect"
        assert connect_sent["params"]["auth"]["token"] == "my-secret"

    @pytest.mark.asyncio
    @patch("routers.container_rpc.uuid.uuid4")
    async def test_skips_event_broadcasts_before_rpc_response(self, mock_uuid):
        from routers.container_rpc import _call_gateway_rpc

        mock_uuid.side_effect = ["handshake-id", self.RPC_ID]
        mock_ws = self._make_handshake_ws(
            rpc_payload={"sessions": [{"key": "s1"}]},
            extra_events=[
                {"type": "event", "event": "health", "payload": {"ok": True}},
                {"type": "event", "event": "presence", "payload": {}},
            ],
        )

        with patch("routers.container_rpc.ws_connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_ws)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _call_gateway_rpc(port=19001, token="tok", method="sessions.list")

        assert result == {"sessions": [{"key": "s1"}]}

    @pytest.mark.asyncio
    @patch("routers.container_rpc.uuid.uuid4")
    async def test_raises_on_rpc_error_response(self, mock_uuid):
        from routers.container_rpc import _call_gateway_rpc

        mock_uuid.side_effect = ["handshake-id", self.RPC_ID]
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(
            side_effect=[
                json.dumps({"event": "connect.challenge"}),
                json.dumps({"ok": True}),
                json.dumps({"type": "res", "id": self.RPC_ID, "ok": False, "error": {"message": "method not found"}}),
            ]
        )

        with patch("routers.container_rpc.ws_connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_ws)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(RuntimeError, match="method not found"):
                await _call_gateway_rpc(port=19001, token="tok", method="nonexistent")
