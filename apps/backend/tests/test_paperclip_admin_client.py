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
    """When no session_token is supplied, fall back to the admin Bearer.

    (For real provisioning T11 will pass session_token, but this
    proves the fallback path still works for instance-admin
    scenarios such as listing companies in admin tooling.)
    """
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


async def test_create_company_uses_session_token_when_provided(client_factory):
    """When ``session_token`` is supplied, it overrides the admin Bearer.

    This is the production path: T11 signs the org-owner up via
    Better Auth and passes the resulting session token here so the
    company gets owner-membership for the right user (rather than
    the instance admin).
    """
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["auth"] = req.headers.get("authorization")
        return httpx.Response(201, json={"id": "co_abc"})

    client = client_factory(handler)
    await client.create_company(
        name="acme.example",
        session_token="user-session-xyz",
    )
    assert captured["auth"] == "Bearer user-session-xyz"


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


# ---------------------------------------------------------------------
# Better Auth (per-user accounts)
# ---------------------------------------------------------------------


async def test_sign_up_user_returns_user_and_token(client_factory):
    """``POST /api/auth/sign-up/email`` accepts ``{email, password, name?}``
    and returns ``{user, token}`` (plus a Set-Cookie for the session).
    """
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["url"] = str(req.url)
        captured["method"] = req.method
        captured["auth"] = req.headers.get("authorization")
        captured["body"] = req.read().decode()
        return httpx.Response(
            200,
            json={
                "user": {"id": "pc_user_1", "email": "alice@isol8.co", "name": "Alice"},
                "token": "sess_token_abc",
            },
            headers={"Set-Cookie": "paperclip-default-session=sess_token_abc; Path=/; HttpOnly"},
        )

    client = client_factory(handler)
    out = await client.sign_up_user(
        email="alice@isol8.co",
        password="random-pass-xyz",
        name="Alice",
    )
    assert captured["method"] == "POST"
    assert "/api/auth/sign-up/email" in captured["url"]
    # Sign-up MUST NOT carry the admin Bearer — Better Auth's
    # disableSignUp flag is the only gate, and the route is
    # unauthenticated.
    assert captured["auth"] is None
    body = _json.loads(captured["body"])
    assert body == {
        "email": "alice@isol8.co",
        "password": "random-pass-xyz",
        "name": "Alice",
    }
    assert out["user"]["id"] == "pc_user_1"
    assert out["token"] == "sess_token_abc"


async def test_sign_up_user_defaults_name_to_email(client_factory):
    """If ``name`` is omitted, fall back to ``email`` so the Better
    Auth payload is always complete (the underlying schema requires
    a non-empty name)."""
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["body"] = req.read().decode()
        return httpx.Response(200, json={"user": {"id": "u"}, "token": "t"})

    client = client_factory(handler)
    await client.sign_up_user(email="bob@isol8.co", password="pw")
    body = _json.loads(captured["body"])
    assert body["name"] == "bob@isol8.co"


async def test_sign_in_user_returns_session_token(client_factory):
    """``POST /api/auth/sign-in/email`` returns ``{user, token}`` with
    the session token in the body (also valid as Bearer)."""
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["url"] = str(req.url)
        captured["body"] = req.read().decode()
        return httpx.Response(
            200,
            json={
                "user": {"id": "pc_user_1", "email": "alice@isol8.co"},
                "token": "sess_signed_in",
            },
        )

    client = client_factory(handler)
    out = await client.sign_in_user(
        email="alice@isol8.co",
        password="random-pass-xyz",
    )
    assert "/api/auth/sign-in/email" in captured["url"]
    body = _json.loads(captured["body"])
    assert body == {"email": "alice@isol8.co", "password": "random-pass-xyz"}
    assert out["token"] == "sess_signed_in"


# ---------------------------------------------------------------------
# Invite-flow chain
# ---------------------------------------------------------------------


async def test_create_company_as_user_uses_session_token_in_authorization(
    client_factory,
):
    """When provisioning the org owner's company, the Bearer must be
    the user's session token (not the admin Bearer) so the new
    company is owned by them."""
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["auth"] = req.headers.get("authorization")
        captured["url"] = str(req.url)
        return httpx.Response(201, json={"id": "co_owned_by_user"})

    client = client_factory(handler)
    out = await client.create_company(
        name="owner@isol8.co",
        session_token="sess_owner",
    )
    assert captured["auth"] == "Bearer sess_owner"
    assert "/api/companies" in captured["url"]
    assert out["id"] == "co_owned_by_user"


async def test_create_invite_targets_company_and_email(client_factory):
    """``create_invite`` POSTs to ``/api/companies/{id}/invites`` with
    ``allowedJoinTypes: "human"`` and a session-token Bearer.

    Note: Paperclip's invite is token-based, NOT email-targeted. The
    ``email`` parameter here is accepted for caller-side audit
    logging only — we don't put it on the wire because Paperclip
    doesn't store it on the invite. We DO assert the ``humanRole``
    field reaches the body when supplied."""
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["url"] = str(req.url)
        captured["auth"] = req.headers.get("authorization")
        captured["body"] = req.read().decode()
        return httpx.Response(
            201,
            json={
                "id": "inv_1",
                "token": "raw-invite-token",
                "companyId": "co_abc",
                "inviteType": "company_join",
                "allowedJoinTypes": "human",
            },
        )

    client = client_factory(handler)
    out = await client.create_invite(
        session_token="sess_admin",
        company_id="co_abc",
        email="newmember@isol8.co",
        human_role="member",
    )
    assert "/api/companies/co_abc/invites" in captured["url"]
    assert captured["auth"] == "Bearer sess_admin"
    body = _json.loads(captured["body"])
    assert body["allowedJoinTypes"] == "human"
    assert body["humanRole"] == "member"
    # Email is not propagated to Paperclip (token-based invite).
    assert "email" not in body
    assert out["token"] == "raw-invite-token"


async def test_accept_invite_with_token(client_factory):
    """``accept_invite`` POSTs to ``/api/invites/{token}/accept`` with
    ``{requestType: "human"}`` and the new member's session token."""
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["url"] = str(req.url)
        captured["auth"] = req.headers.get("authorization")
        captured["body"] = req.read().decode()
        return httpx.Response(
            201,
            json={
                "id": "join_req_1",
                "status": "pending_approval",
                "companyId": "co_abc",
            },
        )

    client = client_factory(handler)
    out = await client.accept_invite(
        session_token="sess_new_member",
        invite_token="raw-invite-token",
    )
    assert "/api/invites/raw-invite-token/accept" in captured["url"]
    assert captured["auth"] == "Bearer sess_new_member"
    body = _json.loads(captured["body"])
    assert body == {"requestType": "human"}
    assert out["status"] == "pending_approval"


async def test_approve_join_request_with_request_id(client_factory):
    """``approve_join_request`` POSTs to
    ``/api/companies/{companyId}/join-requests/{requestId}/approve``
    using a board-admin's session token. Empty body."""
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["url"] = str(req.url)
        captured["auth"] = req.headers.get("authorization")
        captured["body"] = req.read().decode()
        return httpx.Response(
            200,
            json={"id": "join_req_1", "status": "approved"},
        )

    client = client_factory(handler)
    out = await client.approve_join_request(
        session_token="sess_admin",
        company_id="co_abc",
        request_id="join_req_1",
    )
    assert "/api/companies/co_abc/join-requests/join_req_1/approve" in captured["url"]
    assert captured["auth"] == "Bearer sess_admin"
    # Empty body but JSON encoded as "{}"
    assert captured["body"] == "{}"
    assert out["status"] == "approved"
