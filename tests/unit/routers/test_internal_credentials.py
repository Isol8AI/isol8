"""Tests for ECS-style credential vending endpoint."""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch


class TestCredentialEndpoint:
    """Test GET /internal/credentials."""

    @pytest.fixture
    def mock_container_manager(self):
        """Container manager with one running container."""
        from core.containers.manager import ContainerInfo

        info = ContainerInfo(
            user_id="user_abc",
            port=19000,
            container_id="abc123",
            status="running",
            gateway_token="test-gateway-token-xyz",
        )
        manager = MagicMock()
        manager._cache = {"user_abc": info}
        return manager

    @pytest.mark.asyncio
    async def test_returns_credentials_for_valid_token(self, mock_container_manager):
        """Valid gateway_token returns ECS-format credentials."""
        from routers.internal_credentials import get_container_credentials, _credential_cache

        _credential_cache.clear()

        mock_sts = MagicMock()
        mock_sts.assume_role.return_value = {
            "Credentials": {
                "AccessKeyId": "AKIATEST",
                "SecretAccessKey": "secrettest",
                "SessionToken": "tokentest",
                "Expiration": datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc),
            }
        }

        with (
            patch("routers.internal_credentials.get_container_manager", return_value=mock_container_manager),
            patch("routers.internal_credentials.boto3") as mock_boto3,
            patch("routers.internal_credentials.settings") as mock_settings,
        ):
            mock_boto3.client.return_value = mock_sts
            mock_settings.CONTAINER_EXECUTION_ROLE_ARN = "arn:aws:iam::123:role/test-role"

            result = await get_container_credentials(authorization="test-gateway-token-xyz")

        assert result.AccessKeyId == "AKIATEST"
        assert result.SecretAccessKey == "secrettest"
        assert result.Token == "tokentest"
        assert result.Expiration == "2026-03-01T12:00:00Z"

    @pytest.mark.asyncio
    async def test_returns_cached_credentials(self, mock_container_manager):
        """Second call returns cached credentials without calling STS."""
        from routers.internal_credentials import get_container_credentials, _credential_cache

        _credential_cache.clear()

        future_expiry = datetime(2099, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        mock_sts = MagicMock()
        mock_sts.assume_role.return_value = {
            "Credentials": {
                "AccessKeyId": "CACHED",
                "SecretAccessKey": "secret",
                "SessionToken": "token",
                "Expiration": future_expiry,
            }
        }

        with (
            patch("routers.internal_credentials.get_container_manager", return_value=mock_container_manager),
            patch("routers.internal_credentials.boto3") as mock_boto3,
            patch("routers.internal_credentials.settings") as mock_settings,
        ):
            mock_boto3.client.return_value = mock_sts
            mock_settings.CONTAINER_EXECUTION_ROLE_ARN = "arn:aws:iam::123:role/test-role"

            result1 = await get_container_credentials(authorization="test-gateway-token-xyz")
            result2 = await get_container_credentials(authorization="test-gateway-token-xyz")

        assert result1.AccessKeyId == "CACHED"
        assert result2.AccessKeyId == "CACHED"
        mock_sts.assume_role.assert_called_once()

    @pytest.mark.asyncio
    async def test_rejects_invalid_token(self, mock_container_manager):
        """Invalid gateway_token returns 403."""
        from fastapi import HTTPException
        from routers.internal_credentials import get_container_credentials, _credential_cache

        _credential_cache.clear()

        with patch("routers.internal_credentials.get_container_manager", return_value=mock_container_manager):
            with pytest.raises(HTTPException) as exc_info:
                await get_container_credentials(authorization="wrong-token")
            assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_rejects_missing_token(self, mock_container_manager):
        """Missing Authorization header returns 403."""
        from fastapi import HTTPException
        from routers.internal_credentials import get_container_credentials, _credential_cache

        _credential_cache.clear()

        with patch("routers.internal_credentials.get_container_manager", return_value=mock_container_manager):
            with pytest.raises(HTTPException) as exc_info:
                await get_container_credentials(authorization=None)
            assert exc_info.value.status_code == 403


class TestTokenLookup:
    """Test _find_user_by_token helper."""

    def test_finds_user_by_gateway_token(self):
        from core.containers.manager import ContainerInfo
        from routers.internal_credentials import _find_user_by_token

        cache = {
            "user_1": ContainerInfo(
                user_id="user_1",
                port=19000,
                container_id="c1",
                status="running",
                gateway_token="token-1",
            ),
            "user_2": ContainerInfo(
                user_id="user_2",
                port=19001,
                container_id="c2",
                status="running",
                gateway_token="token-2",
            ),
        }
        assert _find_user_by_token(cache, "token-2") == "user_2"

    def test_returns_none_for_unknown_token(self):
        from routers.internal_credentials import _find_user_by_token

        assert _find_user_by_token({}, "unknown") is None


class TestBearerPrefixStripping:
    """Test that Authorization header with Bearer prefix works."""

    @pytest.fixture
    def mock_container_manager(self):
        from core.containers.manager import ContainerInfo

        info = ContainerInfo(
            user_id="user_abc",
            port=19000,
            container_id="abc123",
            status="running",
            gateway_token="test-gateway-token-xyz",
        )
        manager = MagicMock()
        manager._cache = {"user_abc": info}
        return manager

    @pytest.mark.asyncio
    async def test_accepts_bearer_prefixed_token(self, mock_container_manager):
        """Token sent as 'Bearer <token>' should still match."""
        from routers.internal_credentials import get_container_credentials, _credential_cache

        _credential_cache.clear()

        mock_sts = MagicMock()
        mock_sts.assume_role.return_value = {
            "Credentials": {
                "AccessKeyId": "AKIABEARER",
                "SecretAccessKey": "secret",
                "SessionToken": "token",
                "Expiration": datetime(2099, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            }
        }

        with (
            patch("routers.internal_credentials.get_container_manager", return_value=mock_container_manager),
            patch("routers.internal_credentials.boto3") as mock_boto3,
            patch("routers.internal_credentials.settings") as mock_settings,
        ):
            mock_boto3.client.return_value = mock_sts
            mock_settings.CONTAINER_EXECUTION_ROLE_ARN = "arn:aws:iam::123:role/test-role"

            result = await get_container_credentials(authorization="Bearer test-gateway-token-xyz")

        assert result.AccessKeyId == "AKIABEARER"
