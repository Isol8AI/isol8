"""
Tests for BedrockServer agent chat stream methods.

Since bedrock_server.py lives in the enclave and imports enclave-only modules
(crypto_primitives, bedrock_client) that are not on the normal Python path,
we cannot import it directly. Instead, we test by:

1. Mocking the enclave-only imports so BedrockServer can be instantiated
2. Testing command routing and credential handling
"""

import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Mock enclave-only modules so we can import bedrock_server
# ---------------------------------------------------------------------------


@dataclass
class _FakeConverseTurn:
    """Stand-in for bedrock_client.ConverseTurn."""

    role: str
    content: str


def _build_enclave_mocks():
    """
    Create mock modules for crypto_primitives and bedrock_client so that
    ``import bedrock_server`` succeeds in the test environment.

    Returns the mocked bedrock_client module so tests can reference
    ConverseTurn.
    """
    # --- crypto_primitives mock ---
    crypto_mod = types.ModuleType("crypto_primitives")
    fake_keypair = MagicMock()
    fake_keypair.public_key = b"\x00" * 32
    fake_keypair.private_key = b"\x01" * 32
    crypto_mod.generate_x25519_keypair = MagicMock(return_value=fake_keypair)
    crypto_mod.encrypt_to_public_key = MagicMock()
    crypto_mod.decrypt_with_private_key = MagicMock()
    crypto_mod.encrypt_aes_gcm = MagicMock(return_value=(b"\x00" * 16, b"\x01" * 32, b"\x02" * 16))
    crypto_mod.decrypt_aes_gcm = MagicMock(return_value=b"decrypted")
    crypto_mod.EncryptedPayload = MagicMock()
    crypto_mod.KeyPair = MagicMock()
    crypto_mod.bytes_to_hex = lambda b: b.hex() if isinstance(b, bytes) else str(b)
    crypto_mod.hex_to_bytes = bytes.fromhex

    # --- bedrock_client mock ---
    bedrock_mod = types.ModuleType("bedrock_client")
    bedrock_mod.ConverseTurn = _FakeConverseTurn

    mock_bedrock_class = MagicMock()
    mock_bedrock_instance = MagicMock()
    mock_bedrock_instance.has_credentials.return_value = True
    mock_bedrock_class.return_value = mock_bedrock_instance
    bedrock_mod.BedrockClient = mock_bedrock_class
    bedrock_mod.BedrockResponse = MagicMock()
    bedrock_mod.build_converse_messages = MagicMock(return_value=[])

    # --- vsock_http_client mock (imported transitively) ---
    vsock_mod = types.ModuleType("vsock_http_client")
    vsock_mod.VsockHttpClient = MagicMock()

    return crypto_mod, bedrock_mod, vsock_mod


# Install mocks before importing bedrock_server
_crypto_mod, _bedrock_mod, _vsock_mod = _build_enclave_mocks()
sys.modules["crypto_primitives"] = _crypto_mod
sys.modules["bedrock_client"] = _bedrock_mod
sys.modules["vsock_http_client"] = _vsock_mod

# Patch socket.AF_VSOCK which does not exist on macOS/standard Linux
_real_socket = sys.modules.get("socket")

# Now import the module under test
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "enclave"))
from bedrock_server import BedrockServer  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_server() -> BedrockServer:
    """Instantiate a BedrockServer with mocked dependencies."""
    server = BedrockServer.__new__(BedrockServer)
    server.keypair = MagicMock()
    server.keypair.public_key = b"\x00" * 32
    server.keypair.private_key = b"\x01" * 32
    server.bedrock = MagicMock()
    server.bedrock.has_credentials.return_value = True
    server.region = "us-east-1"
    # Gateway fields
    server._gateway = MagicMock()
    server._http_client = MagicMock()
    server._lock = MagicMock()
    server._gateway_started = False
    return server


# ===========================================================================
# Tests for handle_agent_chat_stream command routing
# ===========================================================================


class TestHandleAgentChatStreamRouting:
    """Verify AGENT_CHAT_STREAM is correctly routed in handle_request."""

    def test_agent_chat_stream_returns_none(self):
        """AGENT_CHAT_STREAM is a streaming command, so handle_request returns None."""
        server = _make_server()
        mock_conn = MagicMock()

        # Patch handle_agent_chat_stream to avoid actually running the handler
        with patch.object(server, "handle_agent_chat_stream") as mock_handler:
            result = server.handle_request({"command": "AGENT_CHAT_STREAM"}, mock_conn)

        assert result is None
        mock_handler.assert_called_once_with({"command": "AGENT_CHAT_STREAM"}, mock_conn)

    def test_agent_chat_stream_case_insensitive(self):
        """Command matching is case-insensitive (uppercased)."""
        server = _make_server()
        mock_conn = MagicMock()

        with patch.object(server, "handle_agent_chat_stream") as mock_handler:
            result = server.handle_request({"command": "agent_chat_stream"}, mock_conn)

        assert result is None
        mock_handler.assert_called_once()

    def test_agent_chat_stream_in_available_commands(self):
        """AGENT_CHAT_STREAM appears in the available_commands list for unknown commands."""
        server = _make_server()
        mock_conn = MagicMock()

        result = server.handle_request({"command": "BOGUS_COMMAND"}, mock_conn)

        assert result is not None
        assert result["status"] == "error"
        assert "AGENT_CHAT_STREAM" in result["available_commands"]

    def test_chat_stream_still_works(self):
        """CHAT_STREAM still works correctly alongside AGENT_CHAT_STREAM."""
        server = _make_server()
        mock_conn = MagicMock()

        with patch.object(server, "handle_chat_stream") as mock_handler:
            result = server.handle_request({"command": "CHAT_STREAM"}, mock_conn)

        assert result is None
        mock_handler.assert_called_once()

    def test_non_streaming_commands_return_dict(self):
        """Non-streaming commands like HEALTH return a dict response."""
        server = _make_server()
        mock_conn = MagicMock()

        result = server.handle_request({"command": "HEALTH"}, mock_conn)

        assert result is not None
        assert isinstance(result, dict)
        assert result["command"] == "HEALTH"

    def test_all_known_commands_in_available_list(self):
        """All known commands appear in available_commands error message."""
        server = _make_server()
        mock_conn = MagicMock()

        result = server.handle_request({"command": "UNKNOWN"}, mock_conn)

        expected_commands = [
            "GET_PUBLIC_KEY",
            "SET_CREDENTIALS",
            "HEALTH",
            "CHAT",
            "RUN_TESTS",
            "RUN_AGENT",
            "CHAT_STREAM",
            "AGENT_CHAT_STREAM",
        ]
        for cmd in expected_commands:
            assert cmd in result["available_commands"], f"{cmd} missing from available_commands"


# ===========================================================================
# Tests for handle_set_credentials service_keys handling
# ===========================================================================


class TestSetCredentialsServiceKeys:
    """Tests for service_keys in handle_set_credentials."""

    def _make_creds_data(self, service_keys=None):
        """Build a SET_CREDENTIALS request payload."""
        data = {
            "command": "SET_CREDENTIALS",
            "credentials": {
                "access_key_id": "AKIATEST",
                "secret_access_key": "secret",
                "session_token": "token",
                "expiration": "2026-03-01T00:00:00Z",
            },
        }
        if service_keys is not None:
            data["service_keys"] = service_keys
        return data

    def test_stores_brave_api_key_in_env(self):
        """BRAVE_API_KEY is stored as an env var when provided in service_keys."""
        server = _make_server()
        data = self._make_creds_data(service_keys={"BRAVE_API_KEY": "test-brave-key-123"})

        result = server.handle_set_credentials(data)

        assert result["status"] == "success"
        assert os.environ.get("BRAVE_API_KEY") == "test-brave-key-123"

        # Cleanup
        os.environ.pop("BRAVE_API_KEY", None)

    def test_stores_firecrawl_prefixed_key(self):
        """Keys with FIRECRAWL_ prefix are also stored."""
        server = _make_server()
        data = self._make_creds_data(service_keys={"FIRECRAWL_API_KEY": "fc-key-456"})

        result = server.handle_set_credentials(data)

        assert result["status"] == "success"
        assert os.environ.get("FIRECRAWL_API_KEY") == "fc-key-456"

        # Cleanup
        os.environ.pop("FIRECRAWL_API_KEY", None)

    def test_rejects_disallowed_prefix(self):
        """Keys with disallowed prefixes are NOT stored in env."""
        server = _make_server()
        data = self._make_creds_data(service_keys={"MALICIOUS_VAR": "evil-value"})

        result = server.handle_set_credentials(data)

        assert result["status"] == "success"
        assert "MALICIOUS_VAR" not in os.environ

    def test_rejects_path_injection_key(self):
        """Keys like PATH or LD_PRELOAD are NOT stored."""
        server = _make_server()
        data = self._make_creds_data(service_keys={"PATH": "/evil/bin", "LD_PRELOAD": "/evil.so"})

        original_path = os.environ.get("PATH")
        result = server.handle_set_credentials(data)

        assert result["status"] == "success"
        assert os.environ.get("PATH") == original_path  # Unchanged

    def test_no_service_keys_is_fine(self):
        """When service_keys is absent, credentials still work normally."""
        server = _make_server()
        data = self._make_creds_data()

        result = server.handle_set_credentials(data)

        assert result["status"] == "success"

    def test_empty_service_keys_is_fine(self):
        """When service_keys is empty dict, credentials still work normally."""
        server = _make_server()
        data = self._make_creds_data(service_keys={})

        result = server.handle_set_credentials(data)

        assert result["status"] == "success"

    def test_multiple_allowed_keys_stored(self):
        """Multiple keys with allowed prefixes are all stored."""
        server = _make_server()
        data = self._make_creds_data(
            service_keys={
                "BRAVE_API_KEY": "brave-key",
                "BRAVE_SEARCH_QUOTA": "100",
                "FIRECRAWL_API_KEY": "fc-key",
            }
        )

        result = server.handle_set_credentials(data)

        assert result["status"] == "success"
        assert os.environ.get("BRAVE_API_KEY") == "brave-key"
        assert os.environ.get("BRAVE_SEARCH_QUOTA") == "100"
        assert os.environ.get("FIRECRAWL_API_KEY") == "fc-key"

        # Cleanup
        for key in ["BRAVE_API_KEY", "BRAVE_SEARCH_QUOTA", "FIRECRAWL_API_KEY"]:
            os.environ.pop(key, None)


# ===========================================================================
# Tests for vsock_proxy ALLOWED_HOSTS
# ===========================================================================


class TestVsockProxyAllowlist:
    """Verify vsock_proxy.ALLOWED_HOSTS contains required hosts."""

    def test_brave_api_in_allowlist(self):
        """api.search.brave.com is in the proxy allowlist."""
        sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "enclave"))
        import vsock_proxy

        assert "api.search.brave.com" in vsock_proxy.ALLOWED_HOSTS

    def test_aws_hosts_still_present(self):
        """AWS hosts are still in the allowlist after reorganization."""
        sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "enclave"))
        import vsock_proxy

        assert "bedrock-runtime.us-east-1.amazonaws.com" in vsock_proxy.ALLOWED_HOSTS
        assert "kms.us-east-1.amazonaws.com" in vsock_proxy.ALLOWED_HOSTS
        assert "sts.amazonaws.com" in vsock_proxy.ALLOWED_HOSTS
