"""Teams BFF — Skills (read-only)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from . import agents as _agents
from .deps import TeamsContext

router = APIRouter()
_ctx = _agents._ctx


@router.get("/skills")
async def list_skills(ctx: TeamsContext = Depends(_ctx)):
    """List skills available to the caller's company."""
    return await _agents._admin().list_skills(
        company_id=ctx.company_id,
        session_cookie=ctx.session_cookie,
    )
