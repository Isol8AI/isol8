"""Unit tests for user dict structure (DynamoDB items)."""


class TestUserDict:
    """Tests for user dict shape."""

    def test_user_creation_with_id(self):
        """User dict can be created with an ID."""
        user = {"user_id": "user_clerk_123", "created_at": "2026-01-01T00:00:00Z"}
        assert user["user_id"] == "user_clerk_123"

    def test_user_has_created_at(self):
        """User dict includes created_at."""
        user = {"user_id": "user_clerk_123", "created_at": "2026-01-01T00:00:00Z"}
        assert "created_at" in user
