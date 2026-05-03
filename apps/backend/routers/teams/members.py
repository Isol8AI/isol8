"""Teams BFF — Members.

Joins Paperclip ``companyMemberships`` with Clerk user info so the
panel shows email + display name without two RTTs in the browser.
Reuses the ``_resolve_user_email`` helper from
``routers.teams.agents`` (module-public so other Teams routers can
share it). Clerk failures are tolerated — the row still ships, just
with ``email_via_clerk: None``.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from . import agents as _agents
from .deps import TeamsContext

logger = logging.getLogger(__name__)

router = APIRouter()
_ctx = _agents._ctx


@router.get("/members")
async def list_members(ctx: TeamsContext = Depends(_ctx)):
    """List members in the caller's company, enriched with Clerk emails."""
    upstream = await _agents._admin().list_members(
        company_id=ctx.company_id,
        session_cookie=ctx.session_cookie,
    )
    members = upstream.get("members") or upstream.get("items") or []
    enriched = []
    for m in members:
        principal_id = m.get("principalId") or m.get("paperclip_user_id")
        email: str | None = None
        if principal_id:
            try:
                email = await _agents._resolve_user_email(principal_id)
            except Exception:
                # Tolerate Clerk lookup failures: row still ships,
                # just without the joined email.
                logger.exception(
                    "members.list: clerk email lookup failed for %s",
                    principal_id,
                )
                email = None
        enriched.append({**m, "email_via_clerk": email})
    return {"members": enriched}
