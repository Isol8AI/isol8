"""Unit tests for users router."""

import pytest
from unittest.mock import AsyncMock, patch


class TestSyncUser:
    """Tests for POST /api/v1/users/sync endpoint."""

    @pytest.mark.asyncio
    @patch("routers.users.get_ecs_manager")
    @patch("routers.users.container_repo")
    @patch("routers.users.BillingService")
    @patch("routers.users.user_repo")
    async def test_sync_creates_new_user(
        self, mock_repo, mock_billing_cls, mock_container_repo, mock_get_ecs, async_client
    ):
        """Sync creates new user when not exists."""
        mock_repo.get = AsyncMock(return_value=None)
        mock_repo.put = AsyncMock(return_value=None)
        mock_billing_svc = AsyncMock()
        mock_billing_cls.return_value = mock_billing_svc
        mock_container_repo.get_by_owner_id = AsyncMock(return_value=None)
        mock_ecs = AsyncMock()
        mock_ecs.provision_user_container = AsyncMock(return_value="openclaw-test-abc123")
        mock_get_ecs.return_value = mock_ecs

        response = await async_client.post("/api/v1/users/sync")

        assert response.status_code == 200
        assert response.json()["status"] == "created"
        assert response.json()["user_id"] == "user_test_123"
        mock_ecs.provision_user_container.assert_called_once()

    @pytest.mark.asyncio
    @patch("routers.users.get_ecs_manager")
    @patch("routers.users.container_repo")
    @patch("routers.users.user_repo")
    async def test_sync_returns_exists_for_existing_user(
        self, mock_repo, mock_container_repo, mock_get_ecs, async_client
    ):
        """Sync returns 'exists' for existing user."""
        mock_repo.get = AsyncMock(return_value={"user_id": "user_test_123", "created_at": "2026-01-01T00:00:00Z"})
        mock_container_repo.get_by_owner_id = AsyncMock(return_value={"service_name": "existing"})

        response = await async_client.post("/api/v1/users/sync")

        assert response.status_code == 200
        assert response.json()["status"] == "exists"
        assert response.json()["user_id"] == "user_test_123"
        mock_get_ecs.assert_not_called()

    @pytest.mark.asyncio
    async def test_sync_requires_authentication(self, unauthenticated_async_client):
        """Sync requires authentication."""
        response = await unauthenticated_async_client.post("/api/v1/users/sync")
        assert response.status_code in [401, 403]
