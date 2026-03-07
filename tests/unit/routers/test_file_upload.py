"""Tests for file upload endpoint."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from core.auth import get_current_user, AuthContext


@pytest.fixture
def mock_container():
    container = MagicMock()
    container.service_name = "openclaw-abc123"
    container.status = "running"
    return container


@pytest.fixture
def mock_workspace():
    ws = MagicMock()
    ws.ensure_user_dir = MagicMock()
    ws.write_bytes = MagicMock()
    return ws


@pytest.fixture
def auth_override():
    auth = AuthContext(user_id="user_123")

    async def _override():
        return auth

    return _override


@pytest.mark.asyncio
async def test_upload_single_file(app, auth_override, mock_container, mock_workspace):
    """Upload a single file writes to workspace."""
    app.dependency_overrides[get_current_user] = auth_override
    try:
        with (
            patch("routers.container_rpc.get_ecs_manager") as mock_ecs,
            patch("routers.container_rpc.get_workspace", return_value=mock_workspace),
        ):
            mock_ecs.return_value.get_service_status = AsyncMock(return_value=mock_container)

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/container/files",
                    files=[("files", ("test.txt", b"hello world", "text/plain"))],
                )

            assert resp.status_code == 200
            body = resp.json()
            assert len(body["uploaded"]) == 1
            assert body["uploaded"][0]["filename"] == "test.txt"
            assert body["uploaded"][0]["path"] == "uploads/test.txt"
            assert body["uploaded"][0]["size"] == 11

            mock_workspace.write_bytes.assert_called_once_with("user_123", "uploads/test.txt", b"hello world")
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_upload_multiple_files(app, auth_override, mock_container, mock_workspace):
    """Upload multiple files in one request."""
    app.dependency_overrides[get_current_user] = auth_override
    try:
        with (
            patch("routers.container_rpc.get_ecs_manager") as mock_ecs,
            patch("routers.container_rpc.get_workspace", return_value=mock_workspace),
        ):
            mock_ecs.return_value.get_service_status = AsyncMock(return_value=mock_container)

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/container/files",
                    files=[
                        ("files", ("a.txt", b"aaa", "text/plain")),
                        ("files", ("b.csv", b"1,2,3", "text/csv")),
                    ],
                )

            assert resp.status_code == 200
            body = resp.json()
            assert len(body["uploaded"]) == 2
            assert mock_workspace.write_bytes.call_count == 2
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_upload_rejects_oversized_file(app, auth_override, mock_container, mock_workspace):
    """Upload rejects files larger than 10MB."""
    app.dependency_overrides[get_current_user] = auth_override
    try:
        with (
            patch("routers.container_rpc.get_ecs_manager") as mock_ecs,
            patch("routers.container_rpc.get_workspace", return_value=mock_workspace),
        ):
            mock_ecs.return_value.get_service_status = AsyncMock(return_value=mock_container)

            big_data = b"x" * (10 * 1024 * 1024 + 1)
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/container/files",
                    files=[("files", ("big.bin", big_data, "application/octet-stream"))],
                )

            assert resp.status_code == 400
            assert "10MB" in resp.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_upload_no_container(app, auth_override, mock_workspace):
    """Upload returns 404 when user has no container."""
    app.dependency_overrides[get_current_user] = auth_override
    try:
        with (
            patch("routers.container_rpc.get_ecs_manager") as mock_ecs,
            patch("routers.container_rpc.get_workspace", return_value=mock_workspace),
        ):
            mock_ecs.return_value.get_service_status = AsyncMock(return_value=None)

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/container/files",
                    files=[("files", ("test.txt", b"hello", "text/plain"))],
                )

            assert resp.status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_upload_sanitizes_filename(app, auth_override, mock_container, mock_workspace):
    """Upload sanitizes filenames with path traversal attempts."""
    app.dependency_overrides[get_current_user] = auth_override
    try:
        with (
            patch("routers.container_rpc.get_ecs_manager") as mock_ecs,
            patch("routers.container_rpc.get_workspace", return_value=mock_workspace),
        ):
            mock_ecs.return_value.get_service_status = AsyncMock(return_value=mock_container)

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/container/files",
                    files=[("files", ("../../etc/passwd", b"nope", "text/plain"))],
                )

            assert resp.status_code == 200
            body = resp.json()
            assert ".." not in body["uploaded"][0]["filename"]
            assert "/" not in body["uploaded"][0]["filename"]
    finally:
        app.dependency_overrides.pop(get_current_user, None)
