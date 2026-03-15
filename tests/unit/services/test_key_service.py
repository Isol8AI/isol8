"""Tests for KeyService (user BYOK API key management)."""

import pytest
from unittest.mock import patch
from cryptography.fernet import Fernet
from sqlalchemy import select

from core.services.key_service import KeyService, SUPPORTED_TOOLS
from core.encryption import encrypt, decrypt
from models.user_api_key import UserApiKey

# Generate a stable test key for the entire module
_TEST_ENCRYPTION_KEY = Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def encryption_key():
    """Inject a test ENCRYPTION_KEY for all tests in this module."""
    from core.config import settings as _settings
    with patch.object(_settings, "ENCRYPTION_KEY", _TEST_ENCRYPTION_KEY):
        yield


class TestKeyServiceSetKey:
    """Test KeyService.set_key."""

    @pytest.mark.asyncio
    async def test_creates_new_key(self, db_session):
        """set_key inserts a new UserApiKey row for a new tool."""
        svc = KeyService(db_session)
        key = await svc.set_key("user_ks_1", "perplexity", "pplx-secret-123")

        assert key.user_id == "user_ks_1"
        assert key.tool_id == "perplexity"
        assert key.encrypted_key != "pplx-secret-123"  # stored value is ciphertext

        # Verify persisted in DB and decrypts correctly
        result = await db_session.execute(
            select(UserApiKey).where(
                UserApiKey.user_id == "user_ks_1",
                UserApiKey.tool_id == "perplexity",
            )
        )
        stored = result.scalar_one()
        assert decrypt(stored.encrypted_key) == "pplx-secret-123"

    @pytest.mark.asyncio
    async def test_updates_existing_key(self, db_session):
        """set_key updates the key value when the tool is already configured."""
        svc = KeyService(db_session)
        await svc.set_key("user_ks_2", "perplexity", "old-key")
        await svc.set_key("user_ks_2", "perplexity", "new-key")

        result = await db_session.execute(
            select(UserApiKey).where(
                UserApiKey.user_id == "user_ks_2",
                UserApiKey.tool_id == "perplexity",
            )
        )
        rows = result.scalars().all()
        assert len(rows) == 1  # No duplicate rows
        assert decrypt(rows[0].encrypted_key) == "new-key"

    @pytest.mark.asyncio
    async def test_raises_for_unsupported_tool(self, db_session):
        """set_key raises ValueError for unknown tool IDs."""
        svc = KeyService(db_session)
        with pytest.raises(ValueError, match="Unsupported tool"):
            await svc.set_key("user_ks_3", "unknown_tool", "some-key")

    @pytest.mark.asyncio
    async def test_all_supported_tools_accepted(self, db_session):
        """Every tool in SUPPORTED_TOOLS can be set without error."""
        svc = KeyService(db_session)
        for i, tool_id in enumerate(SUPPORTED_TOOLS):
            key = await svc.set_key(f"user_ks_tool_{i}", tool_id, f"key-{i}")
            assert key.tool_id == tool_id

    @pytest.mark.asyncio
    async def test_different_users_same_tool_independent(self, db_session):
        """Different users can set the same tool without conflict."""
        svc = KeyService(db_session)
        await svc.set_key("user_ks_a", "elevenlabs", "key-a")
        await svc.set_key("user_ks_b", "elevenlabs", "key-b")

        result_a = await svc.get_key("user_ks_a", "elevenlabs")
        result_b = await svc.get_key("user_ks_b", "elevenlabs")
        assert result_a == "key-a"
        assert result_b == "key-b"


class TestKeyServiceGetKey:
    """Test KeyService.get_key."""

    @pytest.mark.asyncio
    async def test_returns_stored_key(self, db_session):
        """get_key returns the stored key value."""
        svc = KeyService(db_session)
        await svc.set_key("user_ks_get_1", "firecrawl", "fc-secret")
        result = await svc.get_key("user_ks_get_1", "firecrawl")
        assert result == "fc-secret"

    @pytest.mark.asyncio
    async def test_returns_none_when_not_set(self, db_session):
        """get_key returns None when no key exists for that user/tool."""
        svc = KeyService(db_session)
        result = await svc.get_key("user_ks_nokey", "perplexity")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_different_tool(self, db_session):
        """get_key returns None when querying a different tool than what was set."""
        svc = KeyService(db_session)
        await svc.set_key("user_ks_get_2", "perplexity", "pplx-key")
        result = await svc.get_key("user_ks_get_2", "elevenlabs")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_different_user(self, db_session):
        """get_key returns None when querying a different user's key."""
        svc = KeyService(db_session)
        await svc.set_key("user_ks_owner", "openai_tts", "oai-key")
        result = await svc.get_key("user_ks_other", "openai_tts")
        assert result is None


class TestKeyServiceDeleteKey:
    """Test KeyService.delete_key."""

    @pytest.mark.asyncio
    async def test_deletes_existing_key(self, db_session):
        """delete_key removes the key and returns True."""
        svc = KeyService(db_session)
        await svc.set_key("user_ks_del_1", "perplexity", "to-delete")
        deleted = await svc.delete_key("user_ks_del_1", "perplexity")
        assert deleted is True

        # Confirm gone from DB
        result = await db_session.execute(
            select(UserApiKey).where(
                UserApiKey.user_id == "user_ks_del_1",
                UserApiKey.tool_id == "perplexity",
            )
        )
        assert result.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_returns_false_when_not_found(self, db_session):
        """delete_key returns False when no key exists to delete."""
        svc = KeyService(db_session)
        deleted = await svc.delete_key("user_ks_del_2", "perplexity")
        assert deleted is False

    @pytest.mark.asyncio
    async def test_delete_is_specific_to_tool(self, db_session):
        """Deleting one tool's key leaves other tools intact."""
        svc = KeyService(db_session)
        await svc.set_key("user_ks_del_3", "perplexity", "pplx-key")
        await svc.set_key("user_ks_del_3", "firecrawl", "fc-key")
        await svc.delete_key("user_ks_del_3", "perplexity")

        assert await svc.get_key("user_ks_del_3", "perplexity") is None
        assert await svc.get_key("user_ks_del_3", "firecrawl") == "fc-key"

    @pytest.mark.asyncio
    async def test_delete_is_specific_to_user(self, db_session):
        """Deleting a key for one user leaves other users' keys intact."""
        svc = KeyService(db_session)
        await svc.set_key("user_ks_del_ua", "elevenlabs", "key-ua")
        await svc.set_key("user_ks_del_ub", "elevenlabs", "key-ub")
        await svc.delete_key("user_ks_del_ua", "elevenlabs")

        assert await svc.get_key("user_ks_del_ua", "elevenlabs") is None
        assert await svc.get_key("user_ks_del_ub", "elevenlabs") == "key-ub"


class TestKeyServiceListKeys:
    """Test KeyService.list_keys."""

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_keys(self, db_session):
        svc = KeyService(db_session)
        result = await svc.list_keys("user_ks_list_0")
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_configured_tools(self, db_session):
        """list_keys returns one entry per configured tool."""
        svc = KeyService(db_session)
        await svc.set_key("user_ks_list_1", "perplexity", "pplx-key")
        await svc.set_key("user_ks_list_1", "firecrawl", "fc-key")

        result = await svc.list_keys("user_ks_list_1")
        assert len(result) == 2
        tool_ids = {r["tool_id"] for r in result}
        assert tool_ids == {"perplexity", "firecrawl"}

    @pytest.mark.asyncio
    async def test_includes_display_name(self, db_session):
        """Each list entry includes the human-readable display_name."""
        svc = KeyService(db_session)
        await svc.set_key("user_ks_list_2", "elevenlabs", "el-key")

        result = await svc.list_keys("user_ks_list_2")
        assert len(result) == 1
        assert result[0]["display_name"] == SUPPORTED_TOOLS["elevenlabs"]["display_name"]
        assert result[0]["tool_id"] == "elevenlabs"

    @pytest.mark.asyncio
    async def test_includes_created_at(self, db_session):
        """Each list entry includes a created_at ISO timestamp."""
        svc = KeyService(db_session)
        await svc.set_key("user_ks_list_3", "openai_tts", "oai-key")

        result = await svc.list_keys("user_ks_list_3")
        assert len(result) == 1
        assert result[0]["created_at"] is not None
        # Should be a parseable ISO string
        from datetime import datetime
        datetime.fromisoformat(result[0]["created_at"])

    @pytest.mark.asyncio
    async def test_does_not_include_key_value(self, db_session):
        """list_keys must not expose the actual key value (security)."""
        svc = KeyService(db_session)
        await svc.set_key("user_ks_list_4", "perplexity", "secret-value")

        result = await svc.list_keys("user_ks_list_4")
        for entry in result:
            assert "encrypted_key" not in entry
            assert "secret-value" not in str(entry)

    @pytest.mark.asyncio
    async def test_only_shows_own_user_keys(self, db_session):
        """list_keys only returns keys for the requested user."""
        svc = KeyService(db_session)
        await svc.set_key("user_ks_list_5a", "perplexity", "key-a")
        await svc.set_key("user_ks_list_5b", "firecrawl", "key-b")

        result = await svc.list_keys("user_ks_list_5a")
        assert len(result) == 1
        assert result[0]["tool_id"] == "perplexity"


class TestFernetEncryption:
    """Test Fernet encrypt/decrypt helpers from core.encryption."""

    def test_encrypt_returns_non_empty_string(self):
        """encrypt returns a non-empty string different from the input."""
        # autouse encryption_key fixture provides the ENCRYPTION_KEY
        result = encrypt("my-secret-key")
        assert result != "my-secret-key"
        assert len(result) > 0

    def test_decrypt_recovers_plaintext(self):
        """decrypt reverses encrypt."""
        ciphertext = encrypt("my-secret-key")
        result = decrypt(ciphertext)
        assert result == "my-secret-key"

    def test_encrypt_decrypt_roundtrip(self):
        """encrypt + decrypt round-trips any plaintext."""
        plaintext = "super-secret-api-key-12345"
        assert decrypt(encrypt(plaintext)) == plaintext

    def test_encrypt_raises_without_key(self):
        """encrypt raises RuntimeError when ENCRYPTION_KEY is not set."""
        from core.config import settings as _settings
        with patch.object(_settings, "ENCRYPTION_KEY", ""):
            with pytest.raises(RuntimeError, match="ENCRYPTION_KEY"):
                encrypt("some-key")

    def test_decrypt_raises_for_invalid_ciphertext(self):
        """decrypt raises ValueError for corrupted or wrong-key ciphertext."""
        with pytest.raises(ValueError, match="Failed to decrypt"):
            decrypt("not-valid-ciphertext")

    @pytest.mark.asyncio
    async def test_set_key_encrypts_before_storing(self, db_session):
        """set_key stores an encrypted value, not the raw plaintext."""
        svc = KeyService(db_session)
        key_row = await svc.set_key("user_fernet_1", "perplexity", "plaintext-key")

        assert key_row.encrypted_key != "plaintext-key"
        assert len(key_row.encrypted_key) > 0

    @pytest.mark.asyncio
    async def test_get_key_decrypts_on_retrieval(self, db_session):
        """get_key returns the original plaintext after round-tripping through DB."""
        svc = KeyService(db_session)
        await svc.set_key("user_fernet_2", "firecrawl", "original-key")
        retrieved = await svc.get_key("user_fernet_2", "firecrawl")

        assert retrieved == "original-key"
