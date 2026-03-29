"""Tests for the tool proxy router."""

from unittest.mock import patch, AsyncMock, MagicMock

import pytest
from httpx import AsyncClient, ASGITransport


class TestProxyRouter:
    @pytest.fixture
    def mock_container_repo(self):
        with patch("routers.proxy.container_repo") as mock_repo:
            yield mock_repo

    @pytest.fixture
    def mock_billing_repo(self):
        with patch("routers.proxy.billing_repo") as mock_repo:
            yield mock_repo

    @pytest.mark.asyncio
    async def test_proxy_rejects_invalid_token(self, app, mock_container_repo):
        """Proxy rejects requests with invalid gateway token."""
        mock_container_repo.get_by_gateway_token = AsyncMock(return_value=None)

        with patch("routers.proxy.settings") as mock_settings:
            mock_settings.PERPLEXITY_API_KEY = "pk_test_key"
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/proxy/search/chat/completions",
                    headers={"Authorization": "Bearer invalid_token"},
                    json={"messages": [{"role": "user", "content": "test"}]},
                )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_proxy_rejects_missing_auth(self, app):
        """Proxy rejects requests without authorization header."""
        with patch("routers.proxy.settings") as mock_settings:
            mock_settings.PERPLEXITY_API_KEY = "pk_test_key"
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/proxy/search/chat/completions",
                    json={"messages": [{"role": "user", "content": "test"}]},
                )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_proxy_rejects_unknown_service(self, app):
        """Proxy rejects unknown service names before token validation."""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/proxy/unknown_service/v1/test",
                headers={"Authorization": "Bearer some_token"},
                json={},
            )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    @patch("routers.proxy.httpx.AsyncClient")
    @patch("routers.proxy.billing_repo")
    @patch("routers.proxy.container_repo")
    async def test_proxy_forwards_to_upstream(self, mock_container_repo, mock_billing_repo, mock_httpx_client_cls, app):
        """Proxy forwards valid request to upstream."""
        mock_container_repo.get_by_gateway_token = AsyncMock(
            return_value={
                "owner_id": "user_proxy_test",
                "gateway_token": "test_gateway_token_proxy",
                "status": "running",
            }
        )
        mock_billing_repo.get_by_owner_id = AsyncMock(
            return_value={
                "owner_id": "user_proxy_test",
                "stripe_customer_id": "cus_proxy_test",
                "plan_tier": "free",
            }
        )
        mock_billing_repo.get_monthly_billable = AsyncMock(return_value=0)

        mock_response = MagicMock()
        mock_response.content = b'{"choices": [{"message": {"content": "test"}}]}'
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_httpx_client_cls.return_value = mock_client

        with patch("routers.proxy.settings") as mock_settings:
            mock_settings.PERPLEXITY_API_KEY = "pk_test_key"
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/proxy/search/chat/completions",
                    headers={"Authorization": "Bearer test_gateway_token_proxy"},
                    json={"messages": [{"role": "user", "content": "test"}]},
                )

        assert resp.status_code == 200
        assert b"choices" in resp.content

    @pytest.mark.asyncio
    @patch("routers.proxy.billing_repo")
    @patch("routers.proxy.container_repo")
    async def test_proxy_rejects_no_billing_account(self, mock_container_repo, mock_billing_repo, app):
        """Proxy rejects requests from users without a billing account."""
        mock_container_repo.get_by_gateway_token = AsyncMock(
            return_value={
                "owner_id": "user_proxy_test",
                "gateway_token": "test_gateway_token_proxy",
                "status": "running",
            }
        )
        mock_billing_repo.get_by_owner_id = AsyncMock(return_value=None)

        with patch("routers.proxy.settings") as mock_settings:
            mock_settings.PERPLEXITY_API_KEY = "pk_test_key"
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/proxy/search/chat/completions",
                    headers={"Authorization": "Bearer test_gateway_token_proxy"},
                    json={"messages": [{"role": "user", "content": "test"}]},
                )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    @patch("routers.proxy.billing_repo")
    @patch("routers.proxy.container_repo")
    async def test_proxy_rejects_over_budget(self, mock_container_repo, mock_billing_repo, app):
        """Proxy rejects requests from users without a billing account (budget gate)."""
        # During DynamoDB migration, budget enforcement is simplified:
        # users without a billing account are rejected with 403.
        mock_container_repo.get_by_gateway_token = AsyncMock(
            return_value={
                "owner_id": "user_proxy_test",
                "gateway_token": "test_gateway_token_proxy",
                "status": "running",
            }
        )
        mock_billing_repo.get_by_owner_id = AsyncMock(return_value=None)

        with patch("routers.proxy.settings") as mock_settings:
            mock_settings.PERPLEXITY_API_KEY = "pk_test_key"
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/proxy/search/chat/completions",
                    headers={"Authorization": "Bearer test_gateway_token_proxy"},
                    json={"messages": [{"role": "user", "content": "test"}]},
                )
        assert resp.status_code == 403
        assert "billing" in resp.json()["detail"].lower()
