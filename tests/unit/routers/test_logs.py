"""
Tests for Logs API (routers/logs.py).

TDD: Tests written BEFORE implementation.
"""

import pytest
from unittest.mock import MagicMock, patch


class TestGetLogs:
    @pytest.mark.asyncio
    @patch("routers.logs.get_container_manager")
    async def test_get_recent_logs(self, mock_get_cm, async_client, test_user):
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = 19000
        mock_cm.get_container_logs.return_value = (
            "2026-02-27 10:00 INFO Gateway started\n2026-02-27 10:01 INFO Agent chat started\n"
        )
        mock_get_cm.return_value = mock_cm
        response = await async_client.get("/api/v1/logs")
        assert response.status_code == 200
        data = response.json()
        assert "logs" in data
        assert "lines" in data

    @pytest.mark.asyncio
    @patch("routers.logs.get_container_manager")
    async def test_get_logs_with_limit(self, mock_get_cm, async_client, test_user):
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = 19000
        mock_cm.get_container_logs.return_value = "line1\nline2\n"
        mock_get_cm.return_value = mock_cm
        response = await async_client.get("/api/v1/logs?lines=50")
        assert response.status_code == 200

    @pytest.mark.asyncio
    @patch("routers.logs.get_container_manager")
    async def test_logs_no_container(self, mock_get_cm, async_client, test_user):
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = None
        mock_get_cm.return_value = mock_cm
        response = await async_client.get("/api/v1/logs")
        assert response.status_code == 404


class TestLogsAuth:
    @pytest.mark.asyncio
    async def test_logs_requires_auth(self, unauthenticated_async_client):
        response = await unauthenticated_async_client.get("/api/v1/logs")
        assert response.status_code in (401, 403)
