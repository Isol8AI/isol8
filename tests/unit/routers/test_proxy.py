"""Tests for the tool proxy router."""

import uuid
from unittest.mock import patch, AsyncMock, MagicMock

import pytest
from httpx import AsyncClient, ASGITransport

from models.billing import BillingAccount
from models.container import Container


class TestProxyRouter:
    @pytest.fixture
    async def container(self, db_session):
        c = Container(
            id=uuid.uuid4(),
            user_id="user_proxy_test",
            gateway_token="test_gateway_token_proxy",
            status="running",
        )
        db_session.add(c)
        await db_session.commit()
        return c

    @pytest.fixture
    async def billing_account(self, db_session):
        account = BillingAccount(
            clerk_user_id="user_proxy_test",
            stripe_customer_id="cus_proxy_test",
        )
        db_session.add(account)
        await db_session.commit()
        return account

    @pytest.mark.asyncio
    async def test_proxy_rejects_invalid_token(self, app, override_get_session_factory):
        """Proxy rejects requests with invalid gateway token."""
        with (
            patch("routers.proxy.get_session_factory", override_get_session_factory),
            patch("routers.proxy.settings") as mock_settings,
        ):
            mock_settings.PERPLEXITY_API_KEY = "pk_test_key"
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/proxy/search/chat/completions",
                    headers={"Authorization": "Bearer invalid_token"},
                    json={"messages": [{"role": "user", "content": "test"}]},
                )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_proxy_rejects_missing_auth(self, app, override_get_session_factory):
        """Proxy rejects requests without authorization header."""
        with (
            patch("routers.proxy.get_session_factory", override_get_session_factory),
            patch("routers.proxy.settings") as mock_settings,
        ):
            mock_settings.PERPLEXITY_API_KEY = "pk_test_key"
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/proxy/search/chat/completions",
                    json={"messages": [{"role": "user", "content": "test"}]},
                )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_proxy_rejects_unknown_service(self, app, override_get_session_factory):
        """Proxy rejects unknown service names before token validation."""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/proxy/unknown_service/v1/test",
                headers={"Authorization": "Bearer some_token"},
                json={},
            )
        # Returns 404 because unknown service check happens after auth header parse
        # but the service check is before DB lookup
        assert resp.status_code == 404

    @pytest.mark.asyncio
    @patch("routers.proxy.httpx.AsyncClient")
    @patch("core.services.usage_service.stripe")
    async def test_proxy_forwards_to_upstream(
        self,
        mock_stripe,
        mock_httpx_client_cls,
        app,
        override_get_session_factory,
        db_session,
        container,
        billing_account,
    ):
        """Proxy forwards valid request to upstream and records usage."""
        # Mock httpx response
        mock_response = MagicMock()
        mock_response.content = b'{"choices": [{"message": {"content": "test"}}]}'
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_httpx_client_cls.return_value = mock_client

        with (
            patch("routers.proxy.get_session_factory", override_get_session_factory),
            patch("routers.proxy.settings") as mock_settings,
        ):
            mock_settings.PERPLEXITY_API_KEY = "pk_test_key"
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/proxy/search/chat/completions",
                    headers={"Authorization": f"Bearer {container.gateway_token}"},
                    json={"messages": [{"role": "user", "content": "test"}]},
                )

        assert resp.status_code == 200
        assert b"choices" in resp.content

    @pytest.mark.asyncio
    async def test_proxy_rejects_no_billing_account(self, app, override_get_session_factory, db_session, container):
        """Proxy rejects requests from users without a billing account."""
        with (
            patch("routers.proxy.get_session_factory", override_get_session_factory),
            patch("routers.proxy.settings") as mock_settings,
        ):
            mock_settings.PERPLEXITY_API_KEY = "pk_test_key"
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/proxy/search/chat/completions",
                    headers={"Authorization": f"Bearer {container.gateway_token}"},
                    json={"messages": [{"role": "user", "content": "test"}]},
                )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_proxy_rejects_unconfigured_service(
        self, app, override_get_session_factory, db_session, container, billing_account
    ):
        """Proxy returns 503 when upstream API key is not configured."""
        with (
            patch("routers.proxy.get_session_factory", override_get_session_factory),
            patch("routers.proxy.settings") as mock_settings,
        ):
            mock_settings.PERPLEXITY_API_KEY = ""
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/proxy/search/chat/completions",
                    headers={"Authorization": f"Bearer {container.gateway_token}"},
                    json={"messages": [{"role": "user", "content": "test"}]},
                )
        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_proxy_rejects_over_budget(
        self, app, override_get_session_factory, db_session, container, billing_account
    ):
        """Proxy rejects requests when user exceeds plan budget."""
        with (
            patch("routers.proxy.get_session_factory", override_get_session_factory),
            patch("routers.proxy.settings") as mock_settings,
            patch("routers.proxy.UsageService") as mock_usage_cls,
        ):
            mock_settings.PERPLEXITY_API_KEY = "pk_test_key"
            # Simulate budget exceeded: free tier is 2_000_000 microdollars
            mock_usage = MagicMock()
            mock_usage.get_monthly_billable = AsyncMock(return_value=3_000_000)
            mock_usage_cls.return_value = mock_usage

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/proxy/search/chat/completions",
                    headers={"Authorization": f"Bearer {container.gateway_token}"},
                    json={"messages": [{"role": "user", "content": "test"}]},
                )
        assert resp.status_code == 429
        assert "budget exceeded" in resp.json()["detail"].lower()
