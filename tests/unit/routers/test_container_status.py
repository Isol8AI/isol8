"""Tests for GET /api/v1/container/status endpoint."""

from datetime import datetime, timezone

import pytest

from models.container import Container


class TestContainerStatus:
    """Test GET /api/v1/container/status."""

    @pytest.fixture
    async def container(self, db_session):
        c = Container(
            user_id="user_test_123",
            service_name="openclaw-abc123",
            gateway_token="secret-token-value",
            status="running",
            task_arn="arn:aws:ecs:us-east-1:123456789:task/test-task",
            access_point_id="fsap-test123",
            created_at=datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 15, 14, 0, 0, tzinfo=timezone.utc),
        )
        db_session.add(c)
        await db_session.commit()
        return c

    @pytest.mark.asyncio
    async def test_returns_container_status(self, async_client, container):
        """Should return container metadata for authenticated user."""
        response = await async_client.get("/api/v1/container/status")
        assert response.status_code == 200
        data = response.json()
        assert data["service_name"] == "openclaw-abc123"
        assert data["status"] == "running"
        assert data["region"] == "us-east-1"
        assert "created_at" in data
        assert "updated_at" in data

    @pytest.mark.asyncio
    async def test_excludes_sensitive_fields(self, async_client, container):
        """Should never expose gateway_token, task_arn, or access_point_id."""
        response = await async_client.get("/api/v1/container/status")
        assert response.status_code == 200
        data = response.json()
        assert "gateway_token" not in data
        assert "task_arn" not in data
        assert "access_point_id" not in data
        assert "task_definition_arn" not in data

    @pytest.mark.asyncio
    async def test_returns_404_without_container(self, async_client):
        """Should return 404 when user has no container."""
        response = await async_client.get("/api/v1/container/status")
        assert response.status_code == 404
