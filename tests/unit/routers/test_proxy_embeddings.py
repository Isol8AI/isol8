"""Tests for Bedrock embeddings proxy."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from main import app


@pytest.fixture
def mock_container():
    container = MagicMock()
    container.user_id = "user_123"
    container.gateway_token = "test-token"
    return container


@pytest.fixture
def mock_billing_account():
    account = MagicMock()
    account.id = uuid4()
    account.clerk_user_id = "user_123"
    account.markup_multiplier = Decimal("1.4")
    return account


@pytest.fixture
def mock_bedrock_response():
    return {
        "embedding": [0.1] * 1024,
        "inputTextTokenCount": 5,
    }


@pytest.mark.asyncio
async def test_embeddings_returns_openai_format(mock_container, mock_billing_account, mock_bedrock_response):
    """Proxy returns OpenAI-compatible embedding response."""
    with (
        patch("routers.proxy.get_session_factory") as mock_sf,
        patch("routers.proxy._call_bedrock_embed") as mock_bedrock,
    ):
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(side_effect=[mock_container, mock_billing_account])
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_sf.return_value = MagicMock(return_value=mock_session)

        mock_bedrock.return_value = mock_bedrock_response

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/proxy/embeddings/embeddings",
                json={"model": "titan-embed-v2", "input": "hello world"},
                headers={"Authorization": "Bearer test-token"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["object"] == "list"
        assert len(body["data"]) == 1
        assert body["data"][0]["object"] == "embedding"
        assert len(body["data"][0]["embedding"]) == 1024
        assert body["usage"]["prompt_tokens"] == 5


@pytest.mark.asyncio
async def test_embeddings_batch_input(mock_container, mock_billing_account, mock_bedrock_response):
    """Proxy handles list input (multiple texts)."""
    with (
        patch("routers.proxy.get_session_factory") as mock_sf,
        patch("routers.proxy._call_bedrock_embed") as mock_bedrock,
    ):
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(side_effect=[mock_container, mock_billing_account])
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_sf.return_value = MagicMock(return_value=mock_session)

        mock_bedrock.return_value = mock_bedrock_response

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/proxy/embeddings/embeddings",
                json={"model": "titan-embed-v2", "input": ["hello", "world"]},
                headers={"Authorization": "Bearer test-token"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["data"]) == 2
        assert mock_bedrock.call_count == 2


@pytest.mark.asyncio
async def test_embeddings_records_usage(mock_container, mock_billing_account, mock_bedrock_response):
    """Proxy records tool usage for billing."""
    with (
        patch("routers.proxy.get_session_factory") as mock_sf,
        patch("routers.proxy._call_bedrock_embed") as mock_bedrock,
        patch("routers.proxy.UsageService") as mock_usage_cls,
    ):
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(side_effect=[mock_container, mock_billing_account])
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_sf.return_value = MagicMock(return_value=mock_session)

        mock_bedrock.return_value = mock_bedrock_response

        mock_usage = AsyncMock()
        mock_usage_cls.return_value = mock_usage

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/api/v1/proxy/embeddings/embeddings",
                json={"model": "titan-embed-v2", "input": "hello"},
                headers={"Authorization": "Bearer test-token"},
            )

        mock_usage.record_tool_usage.assert_called_once()
        call_kwargs = mock_usage.record_tool_usage.call_args[1]
        assert call_kwargs["tool_id"] == "bedrock_embeddings"
        assert call_kwargs["quantity"] == 5


@pytest.mark.asyncio
async def test_embeddings_rejects_missing_auth():
    """Proxy rejects requests with no auth."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/proxy/embeddings/embeddings",
            json={"model": "titan-embed-v2", "input": "hello"},
        )
    assert resp.status_code == 401
