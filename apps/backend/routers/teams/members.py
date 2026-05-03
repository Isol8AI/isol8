"""Teams BFF — Members.

Joins Paperclip ``companyMemberships`` with Clerk user info so the
panel shows email + display name without two RTTs in the browser.
Reuses the ``_resolve_user_email`` helper from
``routers.teams.agents`` (module-public so other Teams routers can
share it). Clerk failures are tolerated — the row still ships, just
with ``email_via_clerk: None``.

Email enrichment notes:

  * Paperclip's ``companyMemberships.principalId`` is the
    Better Auth (Paperclip) user id, NOT a Clerk user id. To resolve
    it via ``_resolve_user_email`` (which calls Clerk
    ``get_user(user_id)``) we must first translate principalId →
    Clerk user_id by consulting the ``paperclip-companies`` rows for
    the caller's org (``by-org-id`` GSI).
  * For personal-context users (``ctx.org_id is None``) the caller is
    the only member of their company, so we skip the GSI lookup and
    just check whether the row's principalId matches
    ``ctx.paperclip_user_id``.
  * If a member's principalId isn't in the org map (drift between
    Paperclip and our DDB), we ship the row with
    ``email_via_clerk: None`` rather than 500ing.
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
    # Paperclip's list_members returns either a flat list or a
    # ``{members: [...]}`` envelope depending on caller; mirror the
    # defensive normalization in
    # ``paperclip_provisioning.archive_member`` so a list-shape
    # response doesn't 500 here.
    members: list[dict]
    if isinstance(upstream, list):
        members = upstream
    elif isinstance(upstream, dict):
        members = upstream.get("members") or upstream.get("items") or []
    else:
        members = []

    # Build the Paperclip principalId → Clerk user_id map for this org
    # so we can call _resolve_user_email with the CLERK id (not the
    # Paperclip principalId, which Clerk doesn't know about).
    principal_to_clerk: dict[str, str] = {}
    if ctx.org_id is None:
        # Personal context: the caller is the only member of their
        # company. Skip the GSI lookup and seed the map with their
        # own pairing.
        if ctx.paperclip_user_id:
            principal_to_clerk[ctx.paperclip_user_id] = ctx.user_id
    else:
        try:
            org_rows = await _agents._repo().list_by_org_id(ctx.org_id)
        except Exception:
            # GSI failure shouldn't take down the whole endpoint;
            # we just lose enrichment for this request.
            logger.exception(
                "members.list: list_by_org_id failed for org=%s",
                ctx.org_id,
            )
            org_rows = []
        for row in org_rows:
            paperclip_uid = row.get("paperclip_user_id")
            clerk_uid = row.get("user_id")
            if paperclip_uid and clerk_uid:
                principal_to_clerk[paperclip_uid] = clerk_uid

    enriched = []
    for m in members:
        principal_id = m.get("principalId") or m.get("paperclip_user_id")
        email: str | None = None
        clerk_user_id = principal_to_clerk.get(principal_id) if principal_id else None
        if clerk_user_id:
            try:
                email = await _agents._resolve_user_email(clerk_user_id)
            except Exception:
                # Tolerate Clerk lookup failures: row still ships,
                # just without the joined email.
                logger.exception(
                    "members.list: clerk email lookup failed for clerk_user_id=%s (paperclip principal=%s)",
                    clerk_user_id,
                    principal_id,
                )
                email = None
        enriched.append({**m, "email_via_clerk": email})
    return {"members": enriched}
