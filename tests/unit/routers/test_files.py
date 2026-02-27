"""
Tests for File Upload API (routers/files.py).

TDD: Tests written BEFORE implementation.
Tests workspace file operations inside user's container.
"""

import pytest
from unittest.mock import MagicMock, patch


class TestListWorkspaceFiles:
    """Test GET /api/v1/files/workspace."""

    @pytest.mark.asyncio
    @patch("routers.files.get_container_manager")
    async def test_list_workspace_root(self, mock_get_cm, async_client, test_user):
        """Lists files at workspace root."""
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = 19000
        mock_cm.exec_command.return_value = "agents\nopenclaw.json\n"
        mock_get_cm.return_value = mock_cm

        response = await async_client.get("/api/v1/files/workspace")
        assert response.status_code == 200
        data = response.json()
        assert "files" in data
        assert len(data["files"]) == 2

    @pytest.mark.asyncio
    @patch("routers.files.get_container_manager")
    async def test_list_workspace_subdir(self, mock_get_cm, async_client, test_user):
        """Lists files in a subdirectory."""
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = 19000
        mock_cm.exec_command.return_value = "SOUL.md\nsessions\nmemory\n"
        mock_get_cm.return_value = mock_cm

        response = await async_client.get("/api/v1/files/workspace?path=agents/luna")
        assert response.status_code == 200
        data = response.json()
        assert len(data["files"]) == 3

    @pytest.mark.asyncio
    @patch("routers.files.get_container_manager")
    async def test_list_workspace_no_container(self, mock_get_cm, async_client, test_user):
        """Returns 404 when user has no container."""
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = None
        mock_get_cm.return_value = mock_cm

        response = await async_client.get("/api/v1/files/workspace")
        assert response.status_code == 404


class TestGetFile:
    """Test GET /api/v1/files/workspace/{path}."""

    @pytest.mark.asyncio
    @patch("routers.files.get_container_manager")
    async def test_get_file_content(self, mock_get_cm, async_client, test_user):
        """Downloads a file from workspace."""
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = 19000
        mock_cm.exec_command.return_value = "# Luna\nA friendly agent."
        mock_get_cm.return_value = mock_cm

        response = await async_client.get("/api/v1/files/workspace/agents/luna/SOUL.md")
        assert response.status_code == 200
        data = response.json()
        assert "content" in data
        assert "Luna" in data["content"]

    @pytest.mark.asyncio
    @patch("routers.files.get_container_manager")
    async def test_get_file_path_traversal_blocked(self, mock_get_cm, async_client, test_user):
        """Path traversal attempts are blocked.

        FastAPI/Starlette normalizes URLs with '..' before routing, so
        traversal paths either get a 400 (our validation) or 404 (URL normalization).
        Both are acceptable — the key is it never reaches the exec command.
        """
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = 19000
        mock_get_cm.return_value = mock_cm

        response = await async_client.get("/api/v1/files/workspace/../../etc/passwd")
        assert response.status_code in (400, 404)
        # Ensure no command was executed inside the container
        mock_cm.exec_command.assert_not_called()


class TestUploadFile:
    """Test PUT /api/v1/files/workspace/{path}."""

    @pytest.mark.asyncio
    @patch("routers.files.get_container_manager")
    async def test_upload_file(self, mock_get_cm, async_client, test_user):
        """Uploads a file to workspace."""
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = 19000
        mock_cm.exec_command.return_value = ""
        mock_get_cm.return_value = mock_cm

        response = await async_client.put(
            "/api/v1/files/workspace/agents/luna/SOUL.md",
            json={"content": "# Luna v2\nUpdated personality."},
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    @patch("routers.files.get_container_manager")
    async def test_upload_file_no_container(self, mock_get_cm, async_client, test_user):
        """Returns 404 when user has no container."""
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = None
        mock_get_cm.return_value = mock_cm

        response = await async_client.put(
            "/api/v1/files/workspace/test.txt",
            json={"content": "hello"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    @patch("routers.files.get_container_manager")
    async def test_upload_path_traversal_blocked(self, mock_get_cm, async_client, test_user):
        """Path traversal in upload is blocked."""
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = 19000
        mock_get_cm.return_value = mock_cm

        response = await async_client.put(
            "/api/v1/files/workspace/../../etc/crontab",
            json={"content": "pwned"},
        )
        assert response.status_code in (400, 404)
        mock_cm.exec_command.assert_not_called()


class TestDeleteFile:
    """Test DELETE /api/v1/files/workspace/{path}."""

    @pytest.mark.asyncio
    @patch("routers.files.get_container_manager")
    async def test_delete_file(self, mock_get_cm, async_client, test_user):
        """Deletes a file from workspace."""
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = 19000
        mock_cm.exec_command.return_value = ""
        mock_get_cm.return_value = mock_cm

        response = await async_client.delete("/api/v1/files/workspace/agents/luna/notes.txt")
        assert response.status_code == 204

    @pytest.mark.asyncio
    @patch("routers.files.get_container_manager")
    async def test_delete_path_traversal_blocked(self, mock_get_cm, async_client, test_user):
        """Path traversal in delete is blocked."""
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = 19000
        mock_get_cm.return_value = mock_cm

        response = await async_client.delete("/api/v1/files/workspace/../../../etc/hosts")
        assert response.status_code in (400, 404)
        mock_cm.exec_command.assert_not_called()


class TestAgentFiles:
    """Test agent-specific file operations."""

    @pytest.mark.asyncio
    @patch("routers.files.get_container_manager")
    async def test_list_agent_files(self, mock_get_cm, async_client, test_user):
        """Lists files for a specific agent."""
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = 19000
        mock_cm.exec_command.return_value = "SOUL.md\nsessions\nmemory\n"
        mock_get_cm.return_value = mock_cm

        response = await async_client.get("/api/v1/files/agents/luna")
        assert response.status_code == 200
        data = response.json()
        assert "files" in data

    @pytest.mark.asyncio
    @patch("routers.files.get_container_manager")
    async def test_upload_agent_file(self, mock_get_cm, async_client, test_user):
        """Uploads a file to an agent's directory."""
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = 19000
        mock_cm.exec_command.return_value = ""
        mock_get_cm.return_value = mock_cm

        response = await async_client.put(
            "/api/v1/files/agents/luna/notes.txt",
            json={"content": "Important context about Luna."},
        )
        assert response.status_code == 200


class TestFilesAuth:
    """Test that file endpoints require authentication."""

    @pytest.mark.asyncio
    async def test_workspace_requires_auth(self, unauthenticated_async_client):
        response = await unauthenticated_async_client.get("/api/v1/files/workspace")
        assert response.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_agent_files_requires_auth(self, unauthenticated_async_client):
        response = await unauthenticated_async_client.get("/api/v1/files/agents/luna")
        assert response.status_code in (401, 403)
