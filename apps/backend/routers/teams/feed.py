"""Teams BFF — Activity + Costs + Dashboard.

All three are pure-read aggregation surfaces. Dashboard fans out
into two upstream calls (the dashboard summary and the sidebar
badge counts) and merges them into one response so the panel
renders in a single round-trip.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends

from . import agents as _agents
from .deps import TeamsContext

router = APIRouter()
_ctx = _agents._ctx


def _flatten_dashboard(raw: Any) -> dict:
    """Flatten Paperclip's nested dashboard summary into the scalar shape
    DashboardPanel expects.

    Upstream (``paperclip/server/src/services/dashboard.ts:summary``)
    returns ``{agents: {active, running, paused, error}, tasks:
    {open, inProgress, blocked, done}, costs: {monthSpendCents, ...},
    runActivity: [{date, succeeded, failed, other, total}, ...], ...}``.
    DashboardPanel.tsx renders ``d.agents`` directly inside a Card,
    which throws React error #31 when ``agents`` is an object.

    Mapping:
      - ``agents``    -> sum of ``active`` + ``running``
                        (operational agents; ``paused`` / ``error``
                        excluded — they're not actively contributing)
      - ``openIssues`` -> ``tasks.open``
      - ``runsToday``  -> ``runActivity[-1].total`` (today's row by
                          construction in the upstream service)
      - ``spendCents`` -> ``costs.monthSpendCents``

    Defensive against missing/None sub-fields — every accessor
    short-circuits to 0 if anything's not the expected shape, so a
    forward-compatible upstream addition can't crash the panel.
    """
    if not isinstance(raw, dict):
        return {"agents": 0, "openIssues": 0, "runsToday": 0, "spendCents": 0}

    agents_obj = raw.get("agents")
    if isinstance(agents_obj, dict):
        # Sum every status bucket (active/running/paused/error/idle/...) so
        # the Overview card reflects the total agent count in any steady
        # state — including all-paused or all-idle. Forward-compatible
        # against new buckets added upstream.
        agents_count = sum(int(v) for v in agents_obj.values() if isinstance(v, (int, float)))
    elif isinstance(agents_obj, (int, float)):
        agents_count = int(agents_obj)
    else:
        agents_count = 0

    tasks_obj = raw.get("tasks")
    open_issues = int(tasks_obj.get("open") or 0) if isinstance(tasks_obj, dict) else 0

    costs_obj = raw.get("costs")
    spend_cents = int(costs_obj.get("monthSpendCents") or 0) if isinstance(costs_obj, dict) else 0

    runs_today = 0
    run_activity = raw.get("runActivity")
    if isinstance(run_activity, list) and run_activity:
        last = run_activity[-1]
        if isinstance(last, dict):
            runs_today = int(last.get("total") or 0)

    return {
        "agents": agents_count,
        "openIssues": open_issues,
        "runsToday": runs_today,
        "spendCents": spend_cents,
    }


@router.get("/activity")
async def list_activity(ctx: TeamsContext = Depends(_ctx)):
    """List company activity events."""
    return await _agents._admin().list_activity(
        company_id=ctx.company_id,
        session_cookie=ctx.session_cookie,
    )


@router.get("/costs")
async def get_costs(ctx: TeamsContext = Depends(_ctx)):
    """Fetch the company costs summary."""
    return await _agents._admin().get_costs(
        company_id=ctx.company_id,
        session_cookie=ctx.session_cookie,
    )


@router.get("/dashboard")
async def get_dashboard(ctx: TeamsContext = Depends(_ctx)):
    """Fetch the dashboard, aggregating dashboard summary + sidebar badges
    in parallel so the panel renders in a single browser RTT.

    The upstream Paperclip ``dashboard`` payload uses nested status
    objects (``agents: {active, running, ...}``, ``tasks: {open, ...}``)
    that DashboardPanel renders directly inside a ``<Card value={...}>``
    — that triggers React error #31 ("Objects are not valid as a React
    child"). Flatten to the scalar shape the panel expects before
    returning.
    """
    admin = _agents._admin()
    badges, dash = await asyncio.gather(
        admin.get_sidebar_badges(
            company_id=ctx.company_id,
            session_cookie=ctx.session_cookie,
        ),
        admin.get_dashboard(
            company_id=ctx.company_id,
            session_cookie=ctx.session_cookie,
        ),
    )
    return {"dashboard": _flatten_dashboard(dash), "sidebar_badges": badges}


@router.get("/sidebar-badges")
async def get_sidebar_badges(ctx: TeamsContext = Depends(_ctx)):
    """Fetch the sidebar badge counts on their own.

    Exposed as a separate endpoint (in addition to being aggregated
    into ``/dashboard``) because the global app shell polls badges
    on a faster cadence than the dashboard panel itself.
    """
    return await _agents._admin().get_sidebar_badges(
        company_id=ctx.company_id,
        session_cookie=ctx.session_cookie,
    )
