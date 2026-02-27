"""
Tests for Cron Management API (routers/cron.py).

TDD: Tests written BEFORE implementation.
"""

import json
import pytest
from unittest.mock import MagicMock, patch


class TestListCronJobs:
    """Test GET /api/v1/cron."""

    @pytest.mark.asyncio
    @patch("routers.cron.get_container_manager")
    async def test_list_cron_jobs(self, mock_get_cm, async_client, test_user):
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = 19000
        mock_cm.exec_command.return_value = json.dumps(
            [
                {"id": "cron-1", "schedule": "0 9 * * *", "task": "daily report", "enabled": True},
                {"id": "cron-2", "schedule": "*/30 * * * *", "task": "check email", "enabled": False},
            ]
        )
        mock_get_cm.return_value = mock_cm
        response = await async_client.get("/api/v1/cron")
        assert response.status_code == 200
        data = response.json()
        assert "jobs" in data
        assert len(data["jobs"]) == 2

    @pytest.mark.asyncio
    @patch("routers.cron.get_container_manager")
    async def test_list_cron_no_container(self, mock_get_cm, async_client, test_user):
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = None
        mock_get_cm.return_value = mock_cm
        response = await async_client.get("/api/v1/cron")
        assert response.status_code == 404


class TestCreateCronJob:
    """Test POST /api/v1/cron."""

    @pytest.mark.asyncio
    @patch("routers.cron.get_container_manager")
    async def test_create_cron_job(self, mock_get_cm, async_client, test_user):
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = 19000
        mock_cm.exec_command.return_value = json.dumps({"id": "cron-new", "status": "created"})
        mock_get_cm.return_value = mock_cm
        response = await async_client.post(
            "/api/v1/cron",
            json={
                "schedule": "0 9 * * *",
                "task": "daily summary",
                "enabled": True,
            },
        )
        assert response.status_code == 200
        assert "job" in response.json()


class TestUpdateCronJob:
    """Test PUT /api/v1/cron/{cron_id}."""

    @pytest.mark.asyncio
    @patch("routers.cron.get_container_manager")
    async def test_update_cron_job(self, mock_get_cm, async_client, test_user):
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = 19000
        mock_cm.exec_command.return_value = json.dumps({"id": "cron-1", "status": "updated"})
        mock_get_cm.return_value = mock_cm
        response = await async_client.put(
            "/api/v1/cron/cron-1",
            json={
                "schedule": "0 10 * * *",
                "enabled": False,
            },
        )
        assert response.status_code == 200


class TestDeleteCronJob:
    """Test DELETE /api/v1/cron/{cron_id}."""

    @pytest.mark.asyncio
    @patch("routers.cron.get_container_manager")
    async def test_delete_cron_job(self, mock_get_cm, async_client, test_user):
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = 19000
        mock_cm.exec_command.return_value = ""
        mock_get_cm.return_value = mock_cm
        response = await async_client.delete("/api/v1/cron/cron-1")
        assert response.status_code == 204


class TestRunCronJob:
    """Test POST /api/v1/cron/{cron_id}/run."""

    @pytest.mark.asyncio
    @patch("routers.cron.get_container_manager")
    async def test_run_cron_job(self, mock_get_cm, async_client, test_user):
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = 19000
        mock_cm.exec_command.return_value = json.dumps({"status": "triggered"})
        mock_get_cm.return_value = mock_cm
        response = await async_client.post("/api/v1/cron/cron-1/run")
        assert response.status_code == 200


class TestCronHistory:
    """Test GET /api/v1/cron/{cron_id}/history."""

    @pytest.mark.asyncio
    @patch("routers.cron.get_container_manager")
    async def test_cron_history(self, mock_get_cm, async_client, test_user):
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = 19000
        mock_cm.exec_command.return_value = json.dumps(
            [
                {"run_id": "r1", "started_at": "2026-02-27T09:00:00Z", "status": "success"},
            ]
        )
        mock_get_cm.return_value = mock_cm
        response = await async_client.get("/api/v1/cron/cron-1/history")
        assert response.status_code == 200
        assert "history" in response.json()


class TestCronAuth:
    """Test cron endpoints require auth."""

    @pytest.mark.asyncio
    async def test_cron_requires_auth(self, unauthenticated_async_client):
        response = await unauthenticated_async_client.get("/api/v1/cron")
        assert response.status_code in (401, 403)
