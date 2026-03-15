"""Tests for KeyService (user BYOK API key management)."""

import base64
import pytest
from unittest.mock import MagicMock, patch
from sqlalchemy import select

from core.services.key_service import KeyService, SUPPORTED_TOOLS, _encrypt, _decrypt
from models.user_api_key import UserApiKey


class TestKeyServiceSetKey:
    """Test KeyService.set_key."""

    @pytest.mark.asyncio
    async def test_creates_new_key(self, db_session):
        """set_key inserts a new UserApiKey row for a new tool."""
        svc = KeyService(db_session)
        key = await svc.set_key("user_ks_1", "perplexity", "pplx-secret-123")

        assert key.user_id == "user_ks_1"
        assert key.tool_id == "perplexity"
        assert key.encrypted_key == "pplx-secret-123"

        # Verify persisted in DB
        result = await db_session.execute(
            select(UserApiKey).where(
                UserApiKey.user_id == "user_ks_1",
                UserApiKey.tool_id == "perplexity",
            )
        )
        stored = result.scalar_one()
        assert stored.encrypted_key == "pplx-secret-123"

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
        assert rows[0].encrypted_key == "new-key"

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


class TestKmsEncryption:
    """Test KMS encrypt/decrypt helpers."""

    def test_encrypt_without_kms_returns_plaintext(self):
        """When KMS_API_KEY_ID is unset, _encrypt returns the value unchanged."""
        with patch("core.services.key_service.settings") as mock_settings:
            mock_settings.KMS_API_KEY_ID = ""
            result = _encrypt("my-secret-key")
        assert result == "my-secret-key"

    def test_decrypt_without_kms_returns_plaintext(self):
        """When KMS_API_KEY_ID is unset, _decrypt returns the value unchanged."""
        with patch("core.services.key_service.settings") as mock_settings:
            mock_settings.KMS_API_KEY_ID = ""
            result = _decrypt("stored-value")
        assert result == "stored-value"

    def test_encrypt_calls_kms_when_configured(self):
        """When KMS_API_KEY_ID is set, _encrypt calls KMS and returns base64 ciphertext."""
        fake_ciphertext = b"\xde\xad\xbe\xef"
        mock_kms = MagicMock()
        mock_kms.encrypt.return_value = {"CiphertextBlob": fake_ciphertext}

        with patch("core.services.key_service.settings") as mock_settings, \
             patch("core.services.key_service._get_kms_client", return_value=mock_kms):
            mock_settings.KMS_API_KEY_ID = "arn:aws:kms:us-east-1:123:key/test-key"
            result = _encrypt("my-secret-key")

        mock_kms.encrypt.assert_called_once_with(
            KeyId="arn:aws:kms:us-east-1:123:key/test-key",
            Plaintext=b"my-secret-key",
        )
        assert result == base64.b64encode(fake_ciphertext).decode("utf-8")

    def test_decrypt_calls_kms_when_configured(self):
        """When KMS_API_KEY_ID is set, _decrypt calls KMS and returns the plaintext."""
        fake_ciphertext = b"\xde\xad\xbe\xef"
        stored = base64.b64encode(fake_ciphertext).decode("utf-8")

        mock_kms = MagicMock()
        mock_kms.decrypt.return_value = {"Plaintext": b"my-secret-key"}

        with patch("core.services.key_service.settings") as mock_settings, \
             patch("core.services.key_service._get_kms_client", return_value=mock_kms):
            mock_settings.KMS_API_KEY_ID = "arn:aws:kms:us-east-1:123:key/test-key"
            result = _decrypt(stored)

        mock_kms.decrypt.assert_called_once_with(
            KeyId="arn:aws:kms:us-east-1:123:key/test-key",
            CiphertextBlob=fake_ciphertext,
        )
        assert result == "my-secret-key"

    def test_encrypt_decrypt_roundtrip_with_kms(self):
        """_encrypt + _decrypt round-trips correctly through KMS."""
        plaintext = "super-secret-api-key-12345"
        fake_ciphertext = b"encrypted-blob"
        stored = base64.b64encode(fake_ciphertext).decode("utf-8")

        mock_kms = MagicMock()
        mock_kms.encrypt.return_value = {"CiphertextBlob": fake_ciphertext}
        mock_kms.decrypt.return_value = {"Plaintext": plaintext.encode("utf-8")}

        with patch("core.services.key_service.settings") as mock_settings, \
             patch("core.services.key_service._get_kms_client", return_value=mock_kms):
            mock_settings.KMS_API_KEY_ID = "arn:aws:kms:us-east-1:123:key/test-key"
            encrypted = _encrypt(plaintext)
            decrypted = _decrypt(encrypted)

        assert decrypted == plaintext

    @pytest.mark.asyncio
    async def test_set_key_encrypts_before_storing(self, db_session):
        """set_key should pass the key through _encrypt before writing to DB."""
        fake_ciphertext = b"\xca\xfe\xba\xbe"
        mock_kms = MagicMock()
        mock_kms.encrypt.return_value = {"CiphertextBlob": fake_ciphertext}
        expected_stored = base64.b64encode(fake_ciphertext).decode("utf-8")

        with patch("core.services.key_service.settings") as mock_settings, \
             patch("core.services.key_service._get_kms_client", return_value=mock_kms):
            mock_settings.KMS_API_KEY_ID = "arn:aws:kms:us-east-1:123:key/test-key"
            svc = KeyService(db_session)
            key = await svc.set_key("user_kms_1", "perplexity", "plaintext-key")

        assert key.encrypted_key == expected_stored
        mock_kms.encrypt.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_key_decrypts_on_retrieval(self, db_session):
        """get_key should pass the stored value through _decrypt before returning."""
        fake_ciphertext = b"\xca\xfe\xba\xbe"
        mock_kms = MagicMock()
        mock_kms.encrypt.return_value = {"CiphertextBlob": fake_ciphertext}
        mock_kms.decrypt.return_value = {"Plaintext": b"original-key"}

        with patch("core.services.key_service.settings") as mock_settings, \
             patch("core.services.key_service._get_kms_client", return_value=mock_kms):
            mock_settings.KMS_API_KEY_ID = "arn:aws:kms:us-east-1:123:key/test-key"
            svc = KeyService(db_session)
            await svc.set_key("user_kms_2", "firecrawl", "original-key")
            retrieved = await svc.get_key("user_kms_2", "firecrawl")

        assert retrieved == "original-key"
        mock_kms.decrypt.assert_called_once()
