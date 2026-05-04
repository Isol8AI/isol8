"""Teams BFF — Inbox.

Read-mostly resource. Reuses the shared ``_ctx`` Depends helper and
shared ``_admin()`` singleton from ``routers.teams.agents`` so we
don't duplicate the auth chain or leak a fresh httpx client per
request. ``_admin`` is referenced via the imported module (rather
than imported by name) so unit tests can monkeypatch
``agents._admin`` once and have every Teams router pick it up.

PR #3a expands this from the 49-line tier-1 stub to a full Inbox
surface: filter-aware listing + heartbeat-run + live-run sub-routes.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query

from . import agents as _agents
from .deps import TeamsContext

router = APIRouter()
_ctx = _agents._ctx


# Tab → upstream filter composition. Mirrors what Paperclip's own Inbox.tsx
# does for board users (GET /api/companies/{co}/issues with these filters).
_TAB_FILTERS: dict[str, dict[str, str]] = {
    "mine": {
        "touchedByUserId": "me",
        "inboxArchivedByUserId": "me",
        "status": "in_review,pending,review,todo,in_progress",
    },
    "recent": {
        "status": "in_review,pending,review,todo,in_progress",
    },
    "all": {},
    "unread": {
        "inboxArchivedByUserId": "me",
        "status": "in_review,pending,review,todo,in_progress",
    },
}
# Tabs that don't fetch from issues at all — they live at sibling routes.
# Frontend should hit /teams/inbox/runs, /teams/approvals, etc. directly,
# but if a stale call lands here we return an empty envelope.
_TABS_NOT_ON_ISSUES = frozenset({"approvals", "runs", "joins"})


@router.get("/inbox")
async def list_inbox(
    ctx: TeamsContext = Depends(_ctx),
    tab: Optional[str] = Query(default=None, pattern=r"^(mine|recent|all|unread|approvals|runs|joins)$"),
    status: Optional[str] = Query(default=None, max_length=40),
    project: Optional[str] = Query(default=None, max_length=80),
    assignee: Optional[str] = Query(default=None, max_length=80),
    creator: Optional[str] = Query(default=None, max_length=80),
    search: Optional[str] = Query(default=None, max_length=200),
    limit: Optional[int] = Query(default=None, ge=1, le=500),
):
    """List inbox items for the signed-in board user.

    Calls upstream ``GET /api/companies/{companyId}/issues`` with
    tab-derived filter params. Mirrors what Paperclip's own Inbox.tsx
    does for board users — the prior implementation called
    ``/api/agents/me/inbox-lite`` which is AGENT-ONLY and 401's our
    board-user session cookie.

    Tabs ``approvals`` / ``runs`` / ``joins`` route through sibling
    endpoints (``/teams/approvals``, ``/teams/inbox/runs``,
    ``/teams/inbox/live-runs``); for those tab values this handler
    returns an empty envelope so the frontend can keep one tab handler.
    """
    if tab in _TABS_NOT_ON_ISSUES:
        return {"items": []}

    # Start with the per-tab filter composition (or {} when no tab).
    upstream_params: dict[str, str] = dict(_TAB_FILTERS.get(tab or "", {}))

    # Per-filter overrides. ``status`` from the caller wins over the
    # tab-derived status default — frontend passes status explicitly only
    # when the user picks one in the filters popover.
    if status is not None:
        upstream_params["status"] = status
    if project is not None:
        upstream_params["projectId"] = project
    if assignee is not None:
        upstream_params["assigneeUserId"] = assignee
    if creator is not None:
        upstream_params["createdByUserId"] = creator
    if search is not None:
        upstream_params["search"] = search
    if limit is not None:
        upstream_params["limit"] = str(limit)

    kwargs: dict[str, Any] = {
        "company_id": ctx.company_id,
        "session_cookie": ctx.session_cookie,
    }
    if upstream_params:
        kwargs["params"] = upstream_params

    rows = await _agents._admin().list_issues(**kwargs)

    # Upstream returns either a list or an envelope. Normalize to {items}.
    if isinstance(rows, list):
        items_in = rows
    elif isinstance(rows, dict):
        items_in = rows.get("issues") or rows.get("items") or []
    else:
        items_in = []

    items = [
        {
            "id": row.get("id"),
            "type": row.get("status") or "issue",
            "title": row.get("title") or row.get("identifier") or "(untitled)",
            "createdAt": row.get("updatedAt"),
        }
        for row in items_in
        if isinstance(row, dict)
    ]
    return {"items": items}


@router.post("/inbox/{item_id}/dismiss")
async def dismiss_inbox(item_id: str, ctx: TeamsContext = Depends(_ctx)):
    """Dismiss an inbox item by id."""
    return await _agents._admin().dismiss_inbox_item(
        item_id=item_id,
        session_cookie=ctx.session_cookie,
    )


@router.get("/inbox/runs")
async def list_inbox_runs(ctx: TeamsContext = Depends(_ctx)):
    """List failed heartbeat runs — the source for the Inbox 'Runs' tab.

    Forwards ``status="failed"`` to upstream so we only surface runs
    that actually need user attention.
    """
    return await _agents._admin().list_company_heartbeat_runs(
        company_id=ctx.company_id,
        session_cookie=ctx.session_cookie,
        status="failed",
    )


@router.get("/inbox/live-runs")
async def list_inbox_live_runs(ctx: TeamsContext = Depends(_ctx)):
    """List currently-running heartbeat runs for the 'Live' badge."""
    return await _agents._admin().list_company_live_runs(
        company_id=ctx.company_id,
        session_cookie=ctx.session_cookie,
    )
