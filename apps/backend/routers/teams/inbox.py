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
    """List inbox items for the caller's company."""
    return await _agents._admin().list_inbox(
        company_id=ctx.company_id,
        session_cookie=ctx.session_cookie,
    )


@router.post("/inbox/{item_id}/dismiss")
async def dismiss_inbox(item_id: str, ctx: TeamsContext = Depends(_ctx)):
    """Dismiss an inbox item by id."""
    return await _agents._admin().dismiss_inbox_item(
        item_id=item_id,
        session_cookie=ctx.session_cookie,
    )
