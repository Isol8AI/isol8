"""Unit tests for users router."""

import pytest
from unittest.mock import AsyncMock, patch


class TestSyncUser:
    """Tests for POST /api/v1/users/sync endpoint."""

    @pytest.mark.asyncio
    @patch("routers.users.user_repo")
    async def test_sync_creates_new_user(self, mock_repo, async_client):
        """Sync creates a new /users row when the user doesn't exist."""
        mock_repo.get = AsyncMock(return_value=None)
        mock_repo.put = AsyncMock(return_value=None)

        response = await async_client.post("/api/v1/users/sync")

        assert response.status_code == 200
        assert response.json()["status"] == "created"
        assert response.json()["user_id"] == "user_test_123"

    @pytest.mark.asyncio
    @patch("routers.users.user_repo")
    async def test_sync_returns_exists_for_existing_user(self, mock_repo, async_client):
        """Sync returns 'exists' for existing user."""
        mock_repo.get = AsyncMock(return_value={"user_id": "user_test_123", "created_at": "2026-01-01T00:00:00Z"})

        response = await async_client.post("/api/v1/users/sync")

        assert response.status_code == 200
        assert response.json()["status"] == "exists"
        assert response.json()["user_id"] == "user_test_123"

    @pytest.mark.asyncio
    @patch("core.services.billing_service.billing_repo")
    @patch("core.services.billing_service.stripe")
    @patch("routers.users.user_repo")
    async def test_sync_does_not_create_billing_account(
        self, mock_user_repo, mock_stripe, mock_billing_repo, async_client
    ):
        """Regression: /users/sync must NOT create a billing row.

        Creating billing on sync produced phantom personal-context rows when
        ChatLayout mounted during the transient "Clerk session has no active
        org yet" window. Billing is now created only by POST /billing/checkout.
        """
        mock_user_repo.get = AsyncMock(return_value=None)
        mock_user_repo.put = AsyncMock(return_value=None)

        response = await async_client.post("/api/v1/users/sync")

        assert response.status_code == 200
        # Zero Stripe + repo writes. Sync only touched /users.
        mock_stripe.Customer.create.assert_not_called()
        mock_billing_repo.create_if_not_exists.assert_not_called()

    @pytest.mark.asyncio
    async def test_sync_requires_authentication(self, unauthenticated_async_client):
        """Sync requires authentication."""
        response = await unauthenticated_async_client.post("/api/v1/users/sync")
        assert response.status_code in [401, 403]
