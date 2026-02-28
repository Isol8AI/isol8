"""
Tests for container-aware request routing.

Verifies that:
- _process_agent_chat_background routes to user's container when available
- Users without a container get a clear error
- Agent CRUD routes to container when available
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch  # noqa: F401 — AsyncMock used in FakeSession


class TestContainerAwareAgentChat:
    """Test _process_agent_chat_background with container routing."""

    @pytest.fixture
    def mock_management_api(self):
        """Mock ManagementApiClient."""
        mock = MagicMock()
        mock.send_message = MagicMock(return_value=True)
        return mock

    @pytest.fixture
    def mock_agent_state(self):
        """Mock AgentState returned from DB."""
        state = MagicMock()
        state.id = "agent-uuid-abc"
        state.agent_name = "luna"
        state.soul_content = "# Luna\nA friendly agent."
        return state

    @pytest.mark.asyncio
    async def test_routes_to_user_container_when_available(self, mock_management_api, mock_agent_state):
        """When user has a container, chat streams through per-user GatewayHttpClient."""
        from routers.websocket_chat import _process_agent_chat_background

        mock_container_info = MagicMock()
        mock_container_info.port = 19005
        mock_container_info.status = "running"
        mock_container_info.gateway_token = "test-token"

        mock_container_manager = MagicMock()
        mock_container_manager.get_container_info.return_value = mock_container_info

        mock_gateway_client = MagicMock()
        mock_gateway_client.chat_stream.return_value = iter(["Hello", " ", "world!"])

        with (
            patch("routers.websocket_chat.get_management_api_client", return_value=mock_management_api),
            patch("routers.websocket_chat.get_session_factory") as mock_sf,
            patch("routers.websocket_chat.get_container_manager", return_value=mock_container_manager),
            patch("routers.websocket_chat.GatewayHttpClient", return_value=mock_gateway_client) as MockClient,
        ):

            class FakeSession:
                async def __aenter__(self):
                    return MagicMock()

                async def __aexit__(self, *args):
                    pass

            mock_sf.return_value = MagicMock(return_value=FakeSession())

            await _process_agent_chat_background(
                connection_id="conn-123",
                user_id="user_with_container",
                agent_name="luna",
                message="Hello!",
            )

        # Should have looked up container info
        mock_container_manager.get_container_info.assert_called_once_with("user_with_container")

        # Should have created a per-user GatewayHttpClient with the container's port and token
        MockClient.assert_called_once_with(base_url="http://127.0.0.1:19005", token="test-token")

    @pytest.mark.asyncio
    async def test_no_container_sends_error_to_client(self, mock_management_api, mock_agent_state):
        """Users without a container get an error message."""
        from routers.websocket_chat import _process_agent_chat_background

        mock_container_manager = MagicMock()
        mock_container_manager.get_container_info.return_value = None

        mock_db_result = MagicMock()
        mock_db_result.scalar_one_or_none.return_value = None
        mock_db_session = AsyncMock()
        mock_db_session.execute = AsyncMock(return_value=mock_db_result)

        with (
            patch("routers.websocket_chat.get_management_api_client", return_value=mock_management_api),
            patch("routers.websocket_chat.get_session_factory") as mock_sf,
            patch("routers.websocket_chat.get_container_manager", return_value=mock_container_manager),
        ):

            class FakeSession:
                async def __aenter__(self):
                    return mock_db_session

                async def __aexit__(self, *args):
                    pass

            mock_sf.return_value = MagicMock(return_value=FakeSession())

            await _process_agent_chat_background(
                connection_id="conn-no-container",
                user_id="free_user",
                agent_name="luna",
                message="Hello!",
            )

        calls = mock_management_api.send_message.call_args_list
        assert any(c[0][1]["type"] == "error" and "container" in c[0][1]["message"].lower() for c in calls)

    @pytest.mark.asyncio
    async def test_streams_chunks_to_client_via_management_api(self, mock_management_api, mock_agent_state):
        """Chunks from gateway stream are pushed to client via Management API."""
        from routers.websocket_chat import _process_agent_chat_background

        mock_info = MagicMock(port=19000, status="running", gateway_token="t")
        mock_container_manager = MagicMock()
        mock_container_manager.get_container_info.return_value = mock_info

        mock_gateway_client = MagicMock()
        mock_gateway_client.chat_stream.return_value = iter(["Hello", " world"])

        with (
            patch("routers.websocket_chat.get_management_api_client", return_value=mock_management_api),
            patch("routers.websocket_chat.get_session_factory") as mock_sf,
            patch("routers.websocket_chat.get_container_manager", return_value=mock_container_manager),
            patch("routers.websocket_chat.GatewayHttpClient", return_value=mock_gateway_client),
        ):

            class FakeSession:
                async def __aenter__(self):
                    return MagicMock()

                async def __aexit__(self, *args):
                    pass

            mock_sf.return_value = MagicMock(return_value=FakeSession())

            await _process_agent_chat_background(
                connection_id="conn-789",
                user_id="user_123",
                agent_name="luna",
                message="Hi",
            )

        # Should have sent chunks + done
        calls = mock_management_api.send_message.call_args_list
        assert any(c[0][1]["type"] == "chunk" and c[0][1]["content"] == "Hello" for c in calls)
        assert any(c[0][1]["type"] == "chunk" and c[0][1]["content"] == " world" for c in calls)
        assert calls[-1][0][1]["type"] == "done"

    @pytest.mark.asyncio
    async def test_heartbeat_from_container_stream(self, mock_management_api, mock_agent_state):
        """None chunks (heartbeats) from stream are forwarded as heartbeat messages."""
        from routers.websocket_chat import _process_agent_chat_background

        mock_info = MagicMock(port=19000, status="running", gateway_token="t")
        mock_container_manager = MagicMock()
        mock_container_manager.get_container_info.return_value = mock_info

        mock_gateway_client = MagicMock()
        # None = heartbeat sentinel
        mock_gateway_client.chat_stream.return_value = iter([None, "Hello"])

        with (
            patch("routers.websocket_chat.get_management_api_client", return_value=mock_management_api),
            patch("routers.websocket_chat.get_session_factory") as mock_sf,
            patch("routers.websocket_chat.get_container_manager", return_value=mock_container_manager),
            patch("routers.websocket_chat.GatewayHttpClient", return_value=mock_gateway_client),
        ):

            class FakeSession:
                async def __aenter__(self):
                    return MagicMock()

                async def __aexit__(self, *args):
                    pass

            mock_sf.return_value = MagicMock(return_value=FakeSession())

            await _process_agent_chat_background(
                connection_id="conn-hb",
                user_id="user_123",
                agent_name="luna",
                message="Hi",
            )

        calls = mock_management_api.send_message.call_args_list
        assert any(c[0][1]["type"] == "heartbeat" for c in calls)

    @pytest.mark.asyncio
    async def test_container_user_streams_successfully(self, mock_management_api, mock_agent_state):
        """Users with containers stream successfully without any shared gateway involvement."""
        from routers.websocket_chat import _process_agent_chat_background

        mock_info = MagicMock(port=19000, status="running", gateway_token="t")
        mock_container_manager = MagicMock()
        mock_container_manager.get_container_info.return_value = mock_info

        mock_gateway_client = MagicMock()
        mock_gateway_client.chat_stream.return_value = iter(["Ok"])

        with (
            patch("routers.websocket_chat.get_management_api_client", return_value=mock_management_api),
            patch("routers.websocket_chat.get_session_factory") as mock_sf,
            patch("routers.websocket_chat.get_container_manager", return_value=mock_container_manager),
            patch("routers.websocket_chat.GatewayHttpClient", return_value=mock_gateway_client),
        ):

            class FakeSession:
                async def __aenter__(self):
                    return MagicMock()

                async def __aexit__(self, *args):
                    pass

            mock_sf.return_value = MagicMock(return_value=FakeSession())

            await _process_agent_chat_background(
                connection_id="conn-skip",
                user_id="container_user",
                agent_name="luna",
                message="Hi",
            )

        # Should have streamed and sent done
        calls = mock_management_api.send_message.call_args_list
        assert any(c[0][1]["type"] == "chunk" for c in calls)
        assert calls[-1][0][1]["type"] == "done"

    @pytest.mark.asyncio
    async def test_gateway_error_sends_error_to_client(self, mock_management_api, mock_agent_state):
        """GatewayRequestError during streaming sends error message to client."""
        from routers.websocket_chat import _process_agent_chat_background
        from core.containers import GatewayRequestError

        mock_info = MagicMock(port=19000, status="running", gateway_token="t")
        mock_container_manager = MagicMock()
        mock_container_manager.get_container_info.return_value = mock_info

        mock_gateway_client = MagicMock()
        mock_gateway_client.chat_stream.side_effect = GatewayRequestError("Connection refused")

        with (
            patch("routers.websocket_chat.get_management_api_client", return_value=mock_management_api),
            patch("routers.websocket_chat.get_session_factory") as mock_sf,
            patch("routers.websocket_chat.get_container_manager", return_value=mock_container_manager),
            patch("routers.websocket_chat.GatewayHttpClient", return_value=mock_gateway_client),
        ):

            class FakeSession:
                async def __aenter__(self):
                    return MagicMock()

                async def __aexit__(self, *args):
                    pass

            mock_sf.return_value = MagicMock(return_value=FakeSession())

            await _process_agent_chat_background(
                connection_id="conn-err",
                user_id="user_123",
                agent_name="luna",
                message="Hi",
            )

        # Should send error message to client
        calls = mock_management_api.send_message.call_args_list
        assert any(c[0][1]["type"] == "error" for c in calls)


class TestContainerAwareAgentCRUD:
    """Test agent CRUD endpoints with container-aware routing."""

    @pytest.mark.asyncio
    @patch("routers.agents.get_container_manager")
    async def test_create_agent_with_container(self, mock_get_cm, async_client, test_user):
        """Creating an agent for a user with a container execs inside their container."""
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = 19000
        mock_cm.exec_command.return_value = '{"status": "ok"}'
        mock_get_cm.return_value = mock_cm

        response = await async_client.post(
            "/api/v1/agents",
            json={
                "agent_name": "luna",
                "soul_content": "# Luna\nA friendly agent.",
            },
        )
        assert response.status_code == 201

        # For users with containers, should exec inside container
        mock_cm.get_container_port.assert_called_with(test_user.id)

    @pytest.mark.asyncio
    @patch("routers.agents.get_container_manager")
    async def test_create_agent_without_container_saves_to_db_only(self, mock_get_cm, async_client, test_user):
        """Creating an agent for a user without a container saves to DB only."""
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = None  # No container
        mock_get_cm.return_value = mock_cm

        response = await async_client.post(
            "/api/v1/agents",
            json={"agent_name": "luna"},
        )
        assert response.status_code == 201

    @pytest.mark.asyncio
    @patch("routers.agents.get_container_manager")
    async def test_delete_agent_with_container(self, mock_get_cm, async_client, test_user):
        """Deleting an agent for a user with a container execs inside their container."""
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = 19000
        mock_cm.exec_command.return_value = '{"status": "ok"}'
        mock_get_cm.return_value = mock_cm

        # Create first (need the agent in DB)
        await async_client.post(
            "/api/v1/agents",
            json={"agent_name": "luna"},
        )

        # Delete
        response = await async_client.delete("/api/v1/agents/luna")
        assert response.status_code == 204

    @pytest.mark.asyncio
    @patch("routers.agents.get_container_manager")
    async def test_delete_agent_without_container_succeeds(self, mock_get_cm, async_client, test_user):
        """Deleting an agent for a user without a container still returns 204."""
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = None
        mock_get_cm.return_value = mock_cm

        # Create first
        await async_client.post(
            "/api/v1/agents",
            json={"agent_name": "luna"},
        )

        # Delete
        response = await async_client.delete("/api/v1/agents/luna")
        assert response.status_code == 204

    @pytest.mark.asyncio
    @patch("routers.agents.get_container_manager")
    async def test_update_agent_with_container(self, mock_get_cm, async_client, test_user):
        """Updating soul_content for a user with container writes to container volume."""
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = 19000
        mock_cm.exec_command.return_value = ""
        mock_get_cm.return_value = mock_cm

        # Create first
        await async_client.post(
            "/api/v1/agents",
            json={"agent_name": "luna", "soul_content": "# Luna"},
        )

        # Update
        response = await async_client.put(
            "/api/v1/agents/luna",
            json={"soul_content": "# Luna v2\nUpdated personality."},
        )
        assert response.status_code == 200
