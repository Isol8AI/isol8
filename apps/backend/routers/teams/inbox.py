"""Teams BFF — Inbox.

Read-mostly resource. Reuses the shared ``_ctx`` Depends helper and
shared ``_admin()`` singleton from ``routers.teams.agents`` so we
don't duplicate the auth chain or leak a fresh httpx client per
request. ``_admin`` is referenced via the imported module (rather
than imported by name) so unit tests can monkeypatch
``agents._admin`` once and have every Teams router pick it up. See
Task 6 for the canonical pattern.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from . import agents as _agents
from .deps import TeamsContext

router = APIRouter()
_ctx = _agents._ctx


@router.get("/inbox")
async def list_inbox(ctx: TeamsContext = Depends(_ctx)):
    """List inbox items for the signed-in user.

    Calls ``GET /api/agents/me/inbox-lite`` upstream (see
    ``paperclip/server/src/routes/agents.ts:1545``) and reshapes the
    raw issue array into the ``{items: [...]}`` envelope the
    InboxPanel expects. ``type`` is filled with the upstream
    ``status`` value as a coarse category, and ``createdAt`` is
    populated from ``updatedAt`` since inbox-lite does not surface
    a created timestamp. The ``id`` is the issue id (used for the
    POST .../dismiss path on click).
    """
    rows = await _agents._admin().list_inbox_for_session_user(
        session_cookie=ctx.session_cookie,
    )
    if not isinstance(rows, list):
        # Defensive — upstream contract is an array, but if a future
        # version envelopes it we want to fail soft rather than 500.
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
