"""Typed httpx async client for Paperclip's REST API.

**Auth model** (2026-04-27 pivot): every call that "acts as" a user
carries that user's Better Auth session token as
``Authorization: Bearer <token>``. The session token is returned by
``/api/auth/sign-up/email`` or ``/api/auth/sign-in/email`` (Better
Auth accepts either a session cookie *or* the bearer token in the
header). Used for creating the company, creating an invite from the
org owner, accepting it as the new member, and approving the
resulting join request from a board admin.

The two unauthenticated routes — ``sign_up_user`` and
``sign_in_user`` — hit Better Auth's public endpoints directly and
don't carry any Bearer at all.

Endpoint surface verified against the local Paperclip checkout at
``~/Desktop/paperclip``:

  - Auth (Better Auth): mounted at ``/api/auth/*`` in
    ``server/src/auth/better-auth.ts``. Standard Better Auth routes —
    ``POST /api/auth/sign-up/email`` and
    ``POST /api/auth/sign-in/email`` accept ``{email, password, name?}``
    and respond ``{user, token}`` with a Set-Cookie session cookie.
  - Companies routes: ``server/src/routes/companies.ts``.
  - Agents routes:    ``server/src/routes/agents.ts``.
  - Access / invite routes: ``server/src/routes/access.ts``:
      * ``POST /api/companies/{companyId}/invites`` — create a
        company-join invite (requires ``users:invite`` permission;
        the user behind ``session_token`` must already be a member).
        Body shape: ``createCompanyInviteSchema`` from
        ``packages/shared/src/validators/access.ts:12``:
        ``{allowedJoinTypes: "human"|"agent"|"both", humanRole?, defaultsPayload?, agentMessage?}``.
        Note: invites are NOT email-targeted — they're token-based.
        The returned ``token`` is the credential that any human can
        use to accept.
      * ``POST /api/invites/{token}/accept`` — accept an invite. The
        signed-in actor (Better Auth session) becomes the new
        member. Body: ``acceptInviteSchema`` —
        ``{requestType: "human"|"agent", agentName?, ...}``. For our
        flow we always pass ``requestType: "human"``.
      * ``POST /api/companies/{companyId}/join-requests/{requestId}/approve``
        — approve the resulting pending join request. The signed-in
        actor must hold ``joins:approve`` on the company.

Notable deviations from the original plan template:

  - ``mint_board_api_key`` REMOVED. Paperclip's REST API has no
    per-user board-key minting endpoint; board API keys are only
    mintable via the CLI auth challenge flow
    (``server/src/services/board-auth.ts``). The new auth model
    instead creates a Better Auth account per Isol8 user (see
    ``sign_up_user`` / ``sign_in_user``) and authenticates proxied
    requests with the resulting session token.
  - ``create_company`` body is ``{name, description?, budgetMonthlyCents?}``
    per ``createCompanySchema`` in
    ``packages/shared/src/validators/company.ts``. There is no
    ``ownerEmail`` field — the caller becomes the owner via
    ``access.ensureMembership`` on the server side, using the actor of
    the bearer token (so for org-create we MUST pass the org-owner's
    ``session_token``, not the admin Bearer).
  - ``create_agent`` sends ``adapterType`` as a top-level field separate
    from ``adapterConfig`` — they are distinct fields per
    ``createAgentSchema``.
  - There is no ``disable`` company endpoint; Paperclip only offers
    ``POST /api/companies/{companyId}/archive``. ``disable_company`` is
    therefore mapped onto the archive endpoint.
  - Paperclip does not honor ``Idempotency-Key`` headers today (no
    middleware/route handler reads it). The client still forwards the
    header when callers provide one so that future Paperclip-side
    support can be picked up without changes here.

**Important: ``PAPERCLIP_AUTH_DISABLE_SIGN_UP=true``.**

That env var (read in ``server/src/config.ts``, applied as
``disableSignUp: config.authDisableSignUp`` to Better Auth in
``server/src/auth/better-auth.ts:121``) is enforced by the Better Auth
library itself — when ``true``, the public ``/api/auth/sign-up/email``
route is rejected for ALL callers, including the backend. This means
production cannot call ``sign_up_user`` while the flag is on. The
deployment plan therefore keeps ``PAPERCLIP_AUTH_DISABLE_SIGN_UP`` set
to ``false`` at the Paperclip server level (Paperclip is on a private
subnet, only reachable through our backend, so the public attack
surface is closed at the network edge rather than at the Better Auth
layer). T11 (provisioning) is the one place in the codebase that
calls ``sign_up_user``; it relies on this network-level closure.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


class PaperclipApiError(Exception):
    """Raised when Paperclip returns a non-2xx response.

    DELETE 404s are NOT raised — callers expect "already gone" to be
    a successful no-op for delete operations.

    The ``retryable`` attribute is auto-classified from ``status_code``:
    5xx (server errors) and 429 (rate-limit) are transient and should
    be retried; everything else (4xx state errors) is permanent and
    must not loop. T12's webhook handler reads ``retryable`` to decide
    whether to enqueue the failed event for async retry.
    """

    def __init__(self, message: str, status_code: int, body: Any):
        super().__init__(message)
        self.status_code = status_code
        self.body = body
        # Auto-classify retryability: 5xx + 429 are retryable, everything
        # else (4xx state errors) is not.
        self.retryable: bool = status_code >= 500 or status_code == 429


class PaperclipAdminClient:
    """Async client wrapping the subset of Paperclip's REST API that
    Isol8's provisioning + cleanup paths need.

    The underlying ``httpx.AsyncClient`` is supplied by the caller so
    that it can be shared with other Paperclip-bound code (e.g. proxy
    code in T14/T15) and so its base_url + connection pool can be
    configured once per Paperclip instance.

    Every operation that affects a specific company is invoked with
    a per-user ``session_token`` so the actor recorded in Paperclip's
    activity log + permission check is the right user.
    """

    def __init__(self, http_client: httpx.AsyncClient):
        self._http = http_client

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _headers(
        self,
        session_token: str,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, str]:
        """Build request headers.

        Authenticates as the user behind ``session_token`` via
        ``Authorization: Bearer <session_token>`` (Better Auth accepts
        the session token in either a cookie or the bearer header —
        see ``server/src/auth/better-auth.ts``).
        """
        headers = {
            "Authorization": f"Bearer {session_token}",
            "Content-Type": "application/json",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    async def _post(
        self,
        path: str,
        json: dict,
        session_token: str,
        idempotency_key: Optional[str] = None,
    ) -> dict:
        resp = await self._http.post(
            path,
            json=json,
            headers=self._headers(session_token, idempotency_key=idempotency_key),
        )
        if resp.status_code >= 400:
            raise PaperclipApiError(
                f"POST {path} -> {resp.status_code}",
                status_code=resp.status_code,
                body=resp.text,
            )
        return resp.json() if resp.content else {}

    async def _delete(
        self,
        path: str,
        session_token: str,
    ) -> None:
        resp = await self._http.delete(
            path,
            headers=self._headers(session_token),
        )
        # 404 on delete is treated as already-gone (idempotent cleanup).
        if resp.status_code >= 400 and resp.status_code != 404:
            raise PaperclipApiError(
                f"DELETE {path} -> {resp.status_code}",
                status_code=resp.status_code,
                body=resp.text,
            )

    # ------------------------------------------------------------------
    # Better Auth (per-user accounts)
    # ------------------------------------------------------------------

    async def sign_up_user(
        self,
        *,
        email: str,
        password: str,
        name: Optional[str] = None,
    ) -> dict:
        """Create a Paperclip Better Auth user via ``/api/auth/sign-up/email``.

        Returns the Better Auth response payload, typically
        ``{user: {id, email, name, ...}, token: <session token>}``
        along with a Set-Cookie session cookie on the response (which
        is captured by the proxy router, not this client).

        Auth: this route does NOT require admin auth — anyone can sign
        up. We rely on ``PAPERCLIP_AUTH_DISABLE_SIGN_UP=false`` at the
        Paperclip server (combined with Paperclip being on a private
        subnet behind our backend) to make this safe. See module
        docstring for the network-level posture.
        """
        body: dict[str, Any] = {
            "email": email,
            "password": password,
            "name": name if name is not None else email,
        }
        # NOTE: we do not pass session_token — sign-up is unauthenticated.
        resp = await self._http.post(
            "/api/auth/sign-up/email",
            json=body,
            headers={"Content-Type": "application/json"},
        )
        if resp.status_code >= 400:
            raise PaperclipApiError(
                f"POST /api/auth/sign-up/email -> {resp.status_code}",
                status_code=resp.status_code,
                body=resp.text,
            )
        return resp.json() if resp.content else {}

    async def sign_in_user(self, *, email: str, password: str) -> dict:
        """Sign in via Better Auth ``/api/auth/sign-in/email``.

        Returns ``{user, token}`` from the Better Auth response. The
        Set-Cookie session cookie is on the response's headers — the
        proxy router (T14) is responsible for extracting it and
        forwarding to the browser, scoped to ``.isol8.co``. The
        ``token`` value in the JSON body is also valid for
        Bearer-style auth and is what we hand to subsequent
        ``session_token``-aware methods on this client.
        """
        body = {"email": email, "password": password}
        resp = await self._http.post(
            "/api/auth/sign-in/email",
            json=body,
            headers={"Content-Type": "application/json"},
        )
        if resp.status_code >= 400:
            raise PaperclipApiError(
                f"POST /api/auth/sign-in/email -> {resp.status_code}",
                status_code=resp.status_code,
                body=resp.text,
            )
        return resp.json() if resp.content else {}

    # ------------------------------------------------------------------
    # Companies
    # ------------------------------------------------------------------

    async def create_company(
        self,
        *,
        session_token: str,
        name: str,
        description: Optional[str] = None,
        budget_monthly_cents: int = 0,
        idempotency_key: Optional[str] = None,
    ) -> dict:
        """Create a Paperclip company.

        Maps to ``POST /api/companies`` (see
        ``server/src/routes/companies.ts:267``).

        Server returns ``201`` with the company object including ``id``,
        ``name``, ``description``, ``status``, ``budgetMonthlyCents``,
        ``createdAt``, ``updatedAt``. The bearer token's user is
        automatically granted ``owner`` membership on the new company,
        so callers MUST pass the org-owner's ``session_token`` here.
        """
        body: dict[str, Any] = {"name": name}
        if description is not None:
            body["description"] = description
        if budget_monthly_cents:
            body["budgetMonthlyCents"] = budget_monthly_cents
        return await self._post(
            "/api/companies",
            json=body,
            session_token=session_token,
            idempotency_key=idempotency_key,
        )

    async def disable_company(
        self,
        *,
        session_token: str,
        company_id: str,
        idempotency_key: Optional[str] = None,
    ) -> dict:
        """Soft-disable a company by archiving it.

        Maps to ``POST /api/companies/{companyId}/archive`` (see
        ``server/src/routes/companies.ts:380``). Paperclip has no
        dedicated ``disable`` endpoint; archive is the documented
        equivalent — hides from default listings, preserves data.
        """
        return await self._post(
            f"/api/companies/{company_id}/archive",
            json={},
            session_token=session_token,
            idempotency_key=idempotency_key,
        )

    async def delete_company(
        self,
        *,
        session_token: str,
        company_id: str,
    ) -> None:
        """Hard-delete a company.

        Maps to ``DELETE /api/companies/{companyId}`` (see
        ``server/src/routes/companies.ts:400``). 404 is swallowed so
        cleanup retries are idempotent.
        """
        await self._delete(
            f"/api/companies/{company_id}",
            session_token=session_token,
        )

    # ------------------------------------------------------------------
    # Invite-flow chain (member onboarding)
    # ------------------------------------------------------------------
    #
    # Paperclip's invite flow is intentionally token-based, not
    # email-based: ``createInvite`` returns a one-shot ``token`` that
    # any human accepting it (via ``acceptInvite``) becomes a
    # join_request for. The receiving member must already be signed
    # in (Better Auth session) before they accept — that's the actor
    # who gets bound to the resulting membership.

    async def create_invite(
        self,
        *,
        session_token: str,
        company_id: str,
        email: str,  # noqa: ARG002 - kept for caller-side audit/logging
        human_role: Optional[str] = None,
    ) -> dict:
        """Create a company-join invite as the signed-in admin.

        Maps to ``POST /api/companies/{companyId}/invites``. Body
        shape (per ``createCompanyInviteSchema`` in
        ``packages/shared/src/validators/access.ts:12``)::

            {
              "allowedJoinTypes": "human",   # we never use agent invites here
              "humanRole": "member"|"admin"|null,
              "defaultsPayload": {...}|null,
              "agentMessage": "..."|null
            }

        The response includes ``token`` — the one-shot invite secret
        that a *different* user (the new member) hands back via
        ``accept_invite``. ``email`` is accepted for caller-side
        audit/logging only; Paperclip itself does not bind the invite
        to an email address.
        """
        body: dict[str, Any] = {
            "allowedJoinTypes": "human",
        }
        if human_role is not None:
            body["humanRole"] = human_role
        return await self._post(
            f"/api/companies/{company_id}/invites",
            json=body,
            session_token=session_token,
        )

    async def accept_invite(
        self,
        *,
        session_token: str,
        invite_token: str,
    ) -> dict:
        """Accept an invite as the new member (signed in via session_token).

        Maps to ``POST /api/invites/{token}/accept`` (see
        ``server/src/routes/access.ts:3199``). For human accept the
        body is just ``{requestType: "human"}``; the resulting
        ``join_request`` is returned and starts in
        ``status: "pending_approval"`` until an existing admin
        approves it.
        """
        return await self._post(
            f"/api/invites/{invite_token}/accept",
            json={"requestType": "human"},
            session_token=session_token,
        )

    async def approve_join_request(
        self,
        *,
        session_token: str,
        company_id: str,
        request_id: str,
    ) -> dict:
        """Approve a pending join request as a board admin.

        Maps to ``POST /api/companies/{companyId}/join-requests/{requestId}/approve``
        (see ``server/src/routes/access.ts:3697``). The signed-in
        user behind ``session_token`` must hold ``joins:approve`` on
        the company (every owner does by default).
        """
        return await self._post(
            f"/api/companies/{company_id}/join-requests/{request_id}/approve",
            json={},
            session_token=session_token,
        )

    # ------------------------------------------------------------------
    # Agents
    # ------------------------------------------------------------------

    async def create_agent(
        self,
        *,
        session_token: str,
        company_id: str,
        name: str,
        role: str,
        adapter_type: str,
        adapter_config: dict,
        title: Optional[str] = None,
        capabilities: Optional[str] = None,
        reports_to: Optional[str] = None,
        budget_monthly_cents: int = 0,
        idempotency_key: Optional[str] = None,
    ) -> dict:
        """Create an agent (employee) inside a company.

        Maps to ``POST /api/companies/{companyId}/agents`` (see
        ``server/src/routes/agents.ts:1634``). ``adapterType`` and
        ``adapterConfig`` are sibling fields on the request body per
        ``createAgentSchema`` in
        ``packages/shared/src/validators/agent.ts:47``.
        """
        body: dict[str, Any] = {
            "name": name,
            "role": role,
            "adapterType": adapter_type,
            "adapterConfig": adapter_config,
        }
        if title is not None:
            body["title"] = title
        if capabilities is not None:
            body["capabilities"] = capabilities
        if reports_to is not None:
            body["reportsTo"] = reports_to
        if budget_monthly_cents:
            body["budgetMonthlyCents"] = budget_monthly_cents
        return await self._post(
            f"/api/companies/{company_id}/agents",
            json=body,
            session_token=session_token,
            idempotency_key=idempotency_key,
        )

    async def create_agent_api_key(
        self,
        *,
        session_token: str,
        agent_id: str,
        name: str = "default",
        idempotency_key: Optional[str] = None,
    ) -> dict:
        """Mint a long-lived API key for an agent.

        Maps to ``POST /api/agents/{agentId}/keys`` (see
        ``server/src/routes/agents.ts:2334``). The response includes the
        plaintext ``token`` exactly once — callers MUST store it
        immediately; it is hashed at rest server-side.

        Response shape (per ``createApiKey`` in
        ``server/src/services/agents.ts:607``)::

            {
              "id": "...",
              "name": "default",
              "token": "<plaintext key value>",
              "createdAt": "..."
            }

        This is the closest persistent agent-level credential
        Paperclip's REST API exposes — board API keys are only
        mintable via the CLI auth challenge flow, so the per-agent
        key created here is what T11 (provisioning) hands the seeded
        CEO agent.
        """
        return await self._post(
            f"/api/agents/{agent_id}/keys",
            json={"name": name},
            session_token=session_token,
            idempotency_key=idempotency_key,
        )
