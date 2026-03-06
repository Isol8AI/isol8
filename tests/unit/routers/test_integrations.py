"""Tests for the MCP server integrations router."""

from unittest.mock import patch, MagicMock

import pytest
from httpx import AsyncClient, ASGITransport

from core.auth import get_current_user, AuthContext
from core.containers.workspace import WorkspaceError


class TestIntegrationsRouter:
    """Test /integrations/mcp/servers CRUD endpoints."""

    @pytest.fixture
    def mock_workspace(self):
        """Mock workspace that stores files in memory."""
        files: dict[str, str] = {}
        ws = MagicMock()

        def read_file(user_id: str, path: str) -> str:
            key = f"{user_id}/{path}"
            if key not in files:
                raise WorkspaceError(f"File not found: {path!r}", user_id=user_id)
            return files[key]

        def write_file(user_id: str, path: str, content: str) -> None:
            files[f"{user_id}/{path}"] = content

        ws.read_file = MagicMock(side_effect=read_file)
        ws.write_file = MagicMock(side_effect=write_file)
        ws._files = files
        return ws

    @pytest.fixture
    def auth_override(self):
        auth = AuthContext(user_id="user_integ_test")

        async def _mock():
            return auth

        return _mock

    @pytest.mark.asyncio
    async def test_list_empty_servers(self, app, mock_workspace, auth_override):
        """GET returns empty servers when no config exists."""
        app.dependency_overrides[get_current_user] = auth_override
        with patch("routers.integrations.get_workspace", return_value=mock_workspace):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/api/v1/integrations/mcp/servers")
        app.dependency_overrides.pop(get_current_user, None)
        assert resp.status_code == 200
        assert resp.json()["servers"] == {}

    @pytest.mark.asyncio
    async def test_put_replaces_servers(self, app, mock_workspace, auth_override):
        """PUT replaces the entire servers dict."""
        app.dependency_overrides[get_current_user] = auth_override
        servers = {
            "github": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-github"],
                "env": {"GITHUB_TOKEN": "ghp_test"},
            }
        }
        with patch("routers.integrations.get_workspace", return_value=mock_workspace):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.put(
                    "/api/v1/integrations/mcp/servers",
                    json={"servers": servers},
                )
                assert resp.status_code == 200
                assert "github" in resp.json()["servers"]

                # Verify GET returns the saved servers
                resp2 = await client.get("/api/v1/integrations/mcp/servers")
                assert resp2.json()["servers"]["github"]["command"] == "npx"
        app.dependency_overrides.pop(get_current_user, None)

    @pytest.mark.asyncio
    async def test_patch_adds_server(self, app, mock_workspace, auth_override):
        """PATCH adds a single server entry."""
        app.dependency_overrides[get_current_user] = auth_override
        with patch("routers.integrations.get_workspace", return_value=mock_workspace):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.patch(
                    "/api/v1/integrations/mcp/servers/linear",
                    json={"command": "npx", "args": ["-y", "@linear/mcp"], "env": {}},
                )
                assert resp.status_code == 200
                assert "linear" in resp.json()["servers"]
        app.dependency_overrides.pop(get_current_user, None)

    @pytest.mark.asyncio
    async def test_delete_removes_server(self, app, mock_workspace, auth_override):
        """DELETE removes a server entry."""
        app.dependency_overrides[get_current_user] = auth_override
        with patch("routers.integrations.get_workspace", return_value=mock_workspace):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                # First add a server
                await client.patch(
                    "/api/v1/integrations/mcp/servers/to-remove",
                    json={"command": "echo", "args": [], "env": {}},
                )
                # Then delete it
                resp = await client.delete("/api/v1/integrations/mcp/servers/to-remove")
                assert resp.status_code == 200
                assert "to-remove" not in resp.json()["servers"]
        app.dependency_overrides.pop(get_current_user, None)

    @pytest.mark.asyncio
    async def test_put_rejects_invalid_server(self, app, mock_workspace, auth_override):
        """PUT rejects servers without command field."""
        app.dependency_overrides[get_current_user] = auth_override
        with patch("routers.integrations.get_workspace", return_value=mock_workspace):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.put(
                    "/api/v1/integrations/mcp/servers",
                    json={"servers": {"bad": {"args": ["test"]}}},
                )
        app.dependency_overrides.pop(get_current_user, None)
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_unauthenticated_request_rejected(self, app, mock_workspace):
        """Requests without auth are rejected."""
        with patch("routers.integrations.get_workspace", return_value=mock_workspace):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/api/v1/integrations/mcp/servers")
        assert resp.status_code == 401 or resp.status_code == 403

    @pytest.mark.asyncio
    async def test_round_trip_crud(self, app, mock_workspace, auth_override):
        """Full CRUD round-trip: add, read, update, delete."""
        app.dependency_overrides[get_current_user] = auth_override
        with patch("routers.integrations.get_workspace", return_value=mock_workspace):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                # Add via PATCH
                resp = await client.patch(
                    "/api/v1/integrations/mcp/servers/test-server",
                    json={"command": "node", "args": ["server.js"], "env": {"KEY": "val"}},
                )
                assert resp.status_code == 200
                assert resp.json()["servers"]["test-server"]["command"] == "node"

                # Read via GET
                resp = await client.get("/api/v1/integrations/mcp/servers")
                assert "test-server" in resp.json()["servers"]

                # Update via PATCH (same name, new config)
                resp = await client.patch(
                    "/api/v1/integrations/mcp/servers/test-server",
                    json={"command": "bun", "args": ["run", "server.ts"], "env": {}},
                )
                assert resp.json()["servers"]["test-server"]["command"] == "bun"

                # Delete
                resp = await client.delete("/api/v1/integrations/mcp/servers/test-server")
                assert "test-server" not in resp.json()["servers"]
        app.dependency_overrides.pop(get_current_user, None)
