"""Tests for OpenClaw HTTP client (container communication)."""

from core.containers.http_client import GatewayHttpClient, GatewayRequestError


class TestGatewayHttpClient:
    def test_initialization_default_url(self):
        client = GatewayHttpClient()
        assert client._base_url == "http://127.0.0.1:18789"

    def test_initialization_custom_url(self):
        client = GatewayHttpClient(base_url="http://127.0.0.1:19005")
        assert client._base_url == "http://127.0.0.1:19005"

    def test_initialization_strips_trailing_slash(self):
        client = GatewayHttpClient(base_url="http://127.0.0.1:19005/")
        assert client._base_url == "http://127.0.0.1:19005"


class TestGatewayRequestError:
    def test_error_with_status_code(self):
        error = GatewayRequestError("Connection refused", status_code=502)
        assert str(error) == "Connection refused"
        assert error.status_code == 502

    def test_error_default_status_code(self):
        error = GatewayRequestError("Timeout")
        assert error.status_code == 0
