"""Tests for ClerkSyncService."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from core.services.clerk_sync_service import ClerkSyncService
from models.user import User


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_db():
    """Create a mock database session."""
    db = AsyncMock()
    db.commit = AsyncMock()
    db.add = MagicMock()
    db.delete = AsyncMock()
    return db


def mock_execute_result(item):
    """Create a mock execute result that returns the given item."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=item)
    return mock_result


# =============================================================================
# Test User Sync
# =============================================================================


class TestUserSync:
    """Tests for user sync operations."""

    @pytest.mark.asyncio
    async def test_create_user(self, mock_db):
        """Creates new user from webhook data."""
        mock_db.execute = AsyncMock(return_value=mock_execute_result(None))

        service = ClerkSyncService(mock_db)
        user = await service.create_user({"id": "user_123"})

        assert user.id == "user_123"
        mock_db.add.assert_called()
        mock_db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_create_user_already_exists(self, mock_db):
        """Returns existing user when creating duplicate."""
        existing_user = User(id="user_123")
        mock_db.execute = AsyncMock(return_value=mock_execute_result(existing_user))

        service = ClerkSyncService(mock_db)
        user = await service.create_user({"id": "user_123"})

        assert user.id == "user_123"

    @pytest.mark.asyncio
    async def test_update_user(self, mock_db):
        """Updates existing user."""
        existing_user = User(id="user_123")
        mock_db.execute = AsyncMock(return_value=mock_execute_result(existing_user))

        service = ClerkSyncService(mock_db)
        user = await service.update_user({"id": "user_123"})

        assert user.id == "user_123"
        mock_db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_update_user_not_found_creates(self, mock_db):
        """Creates user if not found during update."""
        mock_db.execute = AsyncMock(
            side_effect=[
                mock_execute_result(None),
                mock_execute_result(None),
            ]
        )

        service = ClerkSyncService(mock_db)
        user = await service.update_user({"id": "user_123"})

        assert user.id == "user_123"
        mock_db.add.assert_called()

    @pytest.mark.asyncio
    async def test_delete_user(self, mock_db):
        """Deletes user."""
        user = User(id="user_123")
        mock_db.execute = AsyncMock(return_value=mock_execute_result(user))

        service = ClerkSyncService(mock_db)
        await service.delete_user({"id": "user_123"})

        mock_db.delete.assert_called_with(user)
        mock_db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_delete_user_not_found(self, mock_db):
        """Handles deletion of non-existent user."""
        mock_db.execute = AsyncMock(return_value=mock_execute_result(None))

        service = ClerkSyncService(mock_db)
        await service.delete_user({"id": "user_123"})

        mock_db.delete.assert_not_called()
