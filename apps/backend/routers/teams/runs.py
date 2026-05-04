"""Teams BFF — Heartbeat Runs.

Read-only resource that surfaces upstream Paperclip's heartbeat-run
detail. Used by the agent-run page that Inbox failed-run rows link into.
Reuses the shared ``_ctx`` Depends helper so auth + session cookie
plumbing is consistent across the Teams BFF.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from . import agents as _agents
from .deps import TeamsContext

router = APIRouter()
_ctx = _agents._ctx


@router.get("/heartbeat-runs/{run_id}")
async def get_run(run_id: str, ctx: TeamsContext = Depends(_ctx)):
    """Fetch a single heartbeat-run by id.

    Maps to upstream ``GET /api/heartbeat-runs/{runId}``. Distinct from
    the legacy ``GET /teams/runs/{id}`` (in ``agents.py``) which targets
    upstream's generic ``/api/runs/{id}``.
    """
    return await _agents._admin().get_heartbeat_run(
        run_id=run_id,
        session_cookie=ctx.session_cookie,
    )
