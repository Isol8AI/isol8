"""Tests for user API key dict structure (DynamoDB items)."""


class TestUserApiKeyDict:
    def test_user_api_key_creation(self):
        key = {
            "user_id": "user_clerk_123",
            "tool_id": "elevenlabs",
            "encrypted_key": "encrypted_data_here",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }
        assert key["user_id"] == "user_clerk_123"
        assert key["tool_id"] == "elevenlabs"
        assert key["encrypted_key"] == "encrypted_data_here"

    def test_user_api_key_has_timestamps(self):
        key = {
            "user_id": "user_1",
            "tool_id": "openai_tts",
            "encrypted_key": "enc",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }
        assert key["created_at"] is not None
        assert key["updated_at"] is not None
