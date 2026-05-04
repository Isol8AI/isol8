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


@router.get("/inbox")
async def list_inbox(
    ctx: TeamsContext = Depends(_ctx),
    # Tab values mirror upstream's inbox-lite tab segments. The original
    # spec listed mine/recent/all/unread as the 4 work-item tabs, but
    # Paperclip's Inbox UI also routes approvals/runs/joins through this
    # same endpoint as separate tabs (Codex P1 on PR #524). Forward the
    # full set so the frontend doesn't 422 on legitimate tab clicks.
    tab: Optional[str] = Query(default=None, pattern=r"^(mine|recent|all|unread|approvals|runs|joins)$"),
    status: Optional[str] = Query(default=None, max_length=40),
    project: Optional[str] = Query(default=None, max_length=80),
    assignee: Optional[str] = Query(default=None, max_length=80),
    creator: Optional[str] = Query(default=None, max_length=80),
    search: Optional[str] = Query(default=None, max_length=200),
    limit: Optional[int] = Query(default=None, ge=1, le=500),
):
    """List inbox items for the signed-in user, filter-aware.

    Calls ``GET /api/agents/me/inbox-lite`` upstream. Filter params are
    forwarded verbatim. Response is reshaped from the raw issue array
    into the ``{items: [...]}`` envelope the InboxPanel expects (kept
    from the tier-1 stub for back-compat — PR #3c will switch the panel
    to consume the full upstream Issue shape).
    """
    params: dict[str, str] = {}
    if tab is not None:
        params["tab"] = tab
    if status is not None:
        params["status"] = status
    if project is not None:
        params["project"] = project
    if assignee is not None:
        params["assignee"] = assignee
    if creator is not None:
        params["creator"] = creator
    if search is not None:
        params["search"] = search
    if limit is not None:
        params["limit"] = str(limit)

    # Only forward ``params`` when at least one filter is set, so the
    # zero-filter call shape stays identical to the tier-1 stub (back-compat
    # with the original unit test + any other existing callers).
    kwargs: dict[str, Any] = {"session_cookie": ctx.session_cookie}
    if params:
        kwargs["params"] = params
    rows = await _agents._admin().list_inbox_for_session_user(**kwargs)
    if not isinstance(rows, list):
        rows = []
    items = [
        {
            "id": row.get("id"),
            "type": row.get("status") or "issue",
            "title": row.get("title") or row.get("identifier") or "(untitled)",
            "createdAt": row.get("updatedAt"),
        }
        for row in rows
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
