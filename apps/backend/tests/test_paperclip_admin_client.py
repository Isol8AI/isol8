"""Tests for paperclip_admin_client using httpx MockTransport.

``asyncio_mode = "auto"`` in pyproject.toml means async test functions
are auto-marked, so no ``@pytest.mark.asyncio`` decorator is needed.
"""

from __future__ import annotations

import json as _json
from typing import Callable

import httpx
import pytest

from core.services.paperclip_admin_client import (
    PaperclipAdminClient,
    PaperclipApiError,
)


def _make_client(handler: Callable[[httpx.Request], httpx.Response]) -> PaperclipAdminClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, base_url="http://paperclip.test")
    return PaperclipAdminClient(http_client=http, admin_token="admin-test-key")


@pytest.fixture
async def client_factory():
    """Yields a factory that builds a client wired to the given response handler.

    The fixture tracks every ``httpx.AsyncClient`` it creates and
    closes them all on teardown so we don't leak sockets between
    tests.
    """
    clients: list[httpx.AsyncClient] = []

    def factory(handler: Callable[[httpx.Request], httpx.Response]) -> PaperclipAdminClient:
        c = _make_client(handler)
        clients.append(c._http)
        return c

    yield factory
    for h in clients:
        await h.aclose()


async def test_create_company_sends_admin_bearer_and_idempotency_key(client_factory):
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["url"] = str(req.url)
        captured["auth"] = req.headers.get("authorization")
        captured["idem"] = req.headers.get("idempotency-key")
        captured["body"] = req.read().decode()
        return httpx.Response(201, json={"id": "co_abc", "name": "u@example.com"})

    client = client_factory(handler)
    company = await client.create_company(
        name="u@example.com",
        description="provisioned by Isol8",
        idempotency_key="user_123",
    )
    assert captured["auth"] == "Bearer admin-test-key"
    assert captured["idem"] == "user_123"
    body = _json.loads(captured["body"])
    assert body["name"] == "u@example.com"
    assert body["description"] == "provisioned by Isol8"
    # Default budget_monthly_cents=0 should not be sent (kept off the
    # wire so server uses its own default behavior).
    assert "budgetMonthlyCents" not in body
    assert company["id"] == "co_abc"


async def test_5xx_raises_paperclip_api_error(client_factory):
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "down"})

    client = client_factory(handler)
    with pytest.raises(PaperclipApiError) as exc:
        await client.create_company(name="x")
    assert exc.value.status_code == 503


async def test_4xx_raises_paperclip_api_error(client_factory):
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid"})

    client = client_factory(handler)
    with pytest.raises(PaperclipApiError) as exc:
        await client.create_company(name="")
    assert exc.value.status_code == 400


async def test_create_agent_api_key_returns_token(client_factory):
    """``POST /api/agents/{id}/keys`` returns ``{id, name, token, createdAt}``.

    Verified against ``server/src/services/agents.ts:createApiKey``.
    """
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["url"] = str(req.url)
        captured["body"] = req.read().decode()
        return httpx.Response(
            201,
            json={
                "id": "key_1",
                "name": "primary",
                "token": "secret-token-value",
                "createdAt": "2026-04-27T00:00:00Z",
            },
        )

    client = client_factory(handler)
    result = await client.create_agent_api_key(
        agent_id="agent_42",
        name="primary",
    )
    assert result["token"] == "secret-token-value"
    assert "/api/agents/agent_42/keys" in captured["url"]
    body = _json.loads(captured["body"])
    assert body == {"name": "primary"}


async def test_create_agent_passes_adapter_type_and_config(client_factory):
    """``adapterType`` and ``adapterConfig`` are sibling fields per
    ``createAgentSchema`` in
    ``packages/shared/src/validators/agent.ts``.
    """
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["url"] = str(req.url)
        captured["body"] = req.read().decode()
        return httpx.Response(201, json={"id": "agent_1"})

    client = client_factory(handler)
    await client.create_agent(
        company_id="co_abc",
        name="Main Agent",
        role="ceo",
        adapter_type="openclaw_gateway",
        adapter_config={
            "url": "wss://ws-dev.isol8.co",
            "authToken": "svc_token_xyz",
            "sessionKeyStrategy": "fixed",
            "sessionKey": "user_123",
        },
    )
    assert "/api/companies/co_abc/agents" in captured["url"]
    body = _json.loads(captured["body"])
    assert body["adapterType"] == "openclaw_gateway"
    assert body["adapterConfig"]["authToken"] == "svc_token_xyz"
    assert body["adapterConfig"]["sessionKey"] == "user_123"
    assert body["role"] == "ceo"


async def test_delete_company_swallows_404(client_factory):
    """404 on DELETE means already gone — must not raise so cleanup
    cron retries are idempotent.
    """

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not found"})

    client = client_factory(handler)
    # Should NOT raise.
    await client.delete_company(company_id="co_gone")


async def test_disable_company_sends_archive_post(client_factory):
    """``disable_company`` is mapped onto Paperclip's
    ``POST /api/companies/{companyId}/archive`` since there is no
    dedicated ``disable`` endpoint upstream.
    """
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["method"] = req.method
        captured["url"] = str(req.url)
        return httpx.Response(200, json={"id": "co_abc", "status": "archived"})

    client = client_factory(handler)
    await client.disable_company(company_id="co_abc")
    assert captured["method"] == "POST"
    assert "/archive" in captured["url"]
