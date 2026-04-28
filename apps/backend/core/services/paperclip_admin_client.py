"""Typed httpx async client for Paperclip's admin API.

Auth: a Bearer token that resolves to a board user inside Paperclip
(see ``server/src/middleware/auth.ts`` — the ``board_key`` source path).
Isol8's backend holds a single instance-admin board API key as the
``admin_token`` and uses it for all admin operations against a
Paperclip instance.

Endpoint surface verified against the local Paperclip checkout at
``~/Desktop/paperclip``:

  - Companies routes:  ``server/src/routes/companies.ts``
  - Agents routes:     ``server/src/routes/agents.ts``
  - API docs:          ``docs/api/companies.md`` and ``docs/api/agents.md``

Notable deviations from the plan template:

  - ``create_company`` body is ``{name, description?, budgetMonthlyCents?}``
    per ``createCompanySchema`` in
    ``packages/shared/src/validators/company.ts``. There is no
    ``ownerEmail`` field — the caller becomes the owner via
    ``access.ensureMembership`` on the server side, using the actor of
    the bearer token.
  - There is no per-user "board API key" minting endpoint exposed by
    Paperclip's REST API. Board API keys are only created via the CLI
    auth challenge flow (``server/src/services/board-auth.ts``). The
    closest persistent agent-level credential that can be created over
    REST is an Agent API key via ``POST /api/agents/{agentId}/keys``,
    so the client exposes ``create_agent_api_key`` (matching the
    Paperclip surface) instead of the plan's notional
    ``mint_board_api_key``. T11 (provisioning) will use this for the
    CEO agent's long-lived API key.
  - ``create_agent`` sends ``adapterType`` as a top-level field separate
    from ``adapterConfig`` — they are distinct fields per
    ``createAgentSchema``. The plan template's nested ``adapterConfig``
    keeps the same internal shape but ``adapterType`` is now a sibling.
  - There is no ``disable`` company endpoint; Paperclip only offers
    ``POST /api/companies/{companyId}/archive``. ``disable_company`` is
    therefore mapped onto the archive endpoint (semantically: hide from
    listings, preserve data) — the documented Paperclip equivalent of
    "soft-disable".
  - Paperclip does not honor ``Idempotency-Key`` headers today (no
    middleware/route handler reads it). The client still forwards the
    header when callers provide one so that future Paperclip-side
    support can be picked up without changes here. Today it is a no-op
    on the server.
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
    """

    def __init__(self, message: str, status_code: int, body: Any):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class PaperclipAdminClient:
    """Async client wrapping the subset of Paperclip's admin REST API
    that Isol8's provisioning + cleanup paths need.

    The underlying ``httpx.AsyncClient`` is supplied by the caller so
    that it can be shared with other Paperclip-bound code (e.g. proxy
    code in T14/T15) and so its base_url + connection pool can be
    configured once per Paperclip instance.
    """

    def __init__(self, http_client: httpx.AsyncClient, admin_token: str):
        self._http = http_client
        self._admin_token = admin_token

    def _headers(self, idempotency_key: Optional[str] = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._admin_token}",
            "Content-Type": "application/json",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    async def _post(
        self,
        path: str,
        json: dict,
        idempotency_key: Optional[str] = None,
    ) -> dict:
        resp = await self._http.post(path, json=json, headers=self._headers(idempotency_key))
        if resp.status_code >= 400:
            raise PaperclipApiError(
                f"POST {path} -> {resp.status_code}",
                status_code=resp.status_code,
                body=resp.text,
            )
        return resp.json() if resp.content else {}

    async def _delete(self, path: str) -> None:
        resp = await self._http.delete(path, headers=self._headers())
        # 404 on delete is treated as already-gone (idempotent cleanup).
        if resp.status_code >= 400 and resp.status_code != 404:
            raise PaperclipApiError(
                f"DELETE {path} -> {resp.status_code}",
                status_code=resp.status_code,
                body=resp.text,
            )

    # ------------------------------------------------------------------
    # Companies
    # ------------------------------------------------------------------

    async def create_company(
        self,
        *,
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
        automatically granted ``owner`` membership on the new company.
        """
        body: dict[str, Any] = {"name": name}
        if description is not None:
            body["description"] = description
        if budget_monthly_cents:
            body["budgetMonthlyCents"] = budget_monthly_cents
        return await self._post("/api/companies", json=body, idempotency_key=idempotency_key)

    async def disable_company(
        self,
        *,
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
            idempotency_key=idempotency_key,
        )

    async def delete_company(self, *, company_id: str) -> None:
        """Hard-delete a company.

        Maps to ``DELETE /api/companies/{companyId}`` (see
        ``server/src/routes/companies.ts:400``). 404 is swallowed so
        cleanup retries are idempotent.
        """
        await self._delete(f"/api/companies/{company_id}")

    # ------------------------------------------------------------------
    # Agents
    # ------------------------------------------------------------------

    async def create_agent(
        self,
        *,
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
            idempotency_key=idempotency_key,
        )

    async def create_agent_api_key(
        self,
        *,
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

        This is the closest persistent credential surface that
        Paperclip's REST API exposes — board API keys are only mintable
        via the CLI auth challenge flow, so for SSO-style provisioning
        we use the per-agent key created here.
        """
        return await self._post(
            f"/api/agents/{agent_id}/keys",
            json={"name": name},
            idempotency_key=idempotency_key,
        )
