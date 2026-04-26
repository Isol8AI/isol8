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


class TestSyncUserProviderChoice:
    """Tests for Plan 3 Task 3: provider_choice persistence on /users/sync."""

    @pytest.mark.asyncio
    @patch("routers.users.user_repo")
    async def test_sync_persists_provider_choice(self, mock_repo, async_client):
        """POST /users/sync with provider_choice persists via user_repo."""
        mock_repo.get = AsyncMock(return_value=None)
        mock_repo.put = AsyncMock(return_value=None)
        mock_repo.set_provider_choice = AsyncMock(return_value=None)

        response = await async_client.post(
            "/api/v1/users/sync",
            json={"provider_choice": "bedrock_claude"},
        )

        assert response.status_code == 200
        mock_repo.set_provider_choice.assert_awaited_once()
        _, kwargs = mock_repo.set_provider_choice.call_args
        assert kwargs["provider_choice"] == "bedrock_claude"
        assert kwargs.get("byo_provider") is None

    @pytest.mark.asyncio
    @patch("routers.users.user_repo")
    async def test_sync_persists_byo_key_with_provider(self, mock_repo, async_client):
        """byo_key + byo_provider together persist both values."""
        mock_repo.get = AsyncMock(return_value={"user_id": "user_test_123", "created_at": "2026-01-01T00:00:00Z"})
        mock_repo.set_provider_choice = AsyncMock(return_value=None)

        response = await async_client.post(
            "/api/v1/users/sync",
            json={"provider_choice": "byo_key", "byo_provider": "openai"},
        )

        assert response.status_code == 200
        mock_repo.set_provider_choice.assert_awaited_once()
        _, kwargs = mock_repo.set_provider_choice.call_args
        assert kwargs["provider_choice"] == "byo_key"
        assert kwargs["byo_provider"] == "openai"

    @pytest.mark.asyncio
    @patch("routers.users.user_repo")
    async def test_sync_byo_key_without_provider_rejected(self, mock_repo, async_client):
        """byo_key without byo_provider is a 400 (or 422 if pydantic catches it)."""
        mock_repo.get = AsyncMock(return_value=None)
        mock_repo.put = AsyncMock(return_value=None)
        mock_repo.set_provider_choice = AsyncMock(return_value=None)

        response = await async_client.post(
            "/api/v1/users/sync",
            json={"provider_choice": "byo_key"},
        )

        assert response.status_code in (400, 422)
        mock_repo.set_provider_choice.assert_not_called()

    @pytest.mark.asyncio
    @patch("routers.users.user_repo")
    async def test_sync_without_provider_choice_unchanged(self, mock_repo, async_client):
        """Existing callers (no body / empty body) bypass set_provider_choice."""
        mock_repo.get = AsyncMock(return_value=None)
        mock_repo.put = AsyncMock(return_value=None)
        mock_repo.set_provider_choice = AsyncMock(return_value=None)

        response = await async_client.post("/api/v1/users/sync", json={})

        assert response.status_code == 200
        mock_repo.set_provider_choice.assert_not_called()

    @pytest.mark.asyncio
    @patch("routers.users.user_repo")
    async def test_sync_no_body_unchanged(self, mock_repo, async_client):
        """No body at all (legacy contract) still works."""
        mock_repo.get = AsyncMock(return_value=None)
        mock_repo.put = AsyncMock(return_value=None)
        mock_repo.set_provider_choice = AsyncMock(return_value=None)

        response = await async_client.post("/api/v1/users/sync")

        assert response.status_code == 200
        mock_repo.set_provider_choice.assert_not_called()

    @pytest.mark.asyncio
    @patch("routers.users.user_repo")
    async def test_sync_invalid_provider_choice_rejected(self, mock_repo, async_client):
        """Unknown provider_choice value is 422 (pydantic Literal)."""
        mock_repo.get = AsyncMock(return_value=None)
        mock_repo.put = AsyncMock(return_value=None)
        mock_repo.set_provider_choice = AsyncMock(return_value=None)

        response = await async_client.post(
            "/api/v1/users/sync",
            json={"provider_choice": "wat"},
        )

        assert response.status_code == 422
        mock_repo.set_provider_choice.assert_not_called()
