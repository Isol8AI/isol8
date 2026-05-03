"""Tests for the Teams Feed BFF (Task 11) — Activity + Costs + Dashboard."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from main import app
from routers.teams.deps import TeamsContext


@pytest.fixture
def teams_ctx():
    return TeamsContext(
        user_id="u1",
        org_id="o1",
        owner_id="o1",
        company_id="co_abc",
        paperclip_user_id="pcu_xyz",
        session_cookie="cookie",
    )


@pytest.fixture
def client(teams_ctx):
    from routers.teams import agents as agents_mod

    async def fake_ctx():
        return teams_ctx

    app.dependency_overrides[agents_mod._ctx] = fake_ctx
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(agents_mod._ctx, None)


def test_list_activity(client, monkeypatch):
    admin = MagicMock()
    admin.list_activity = AsyncMock(return_value={"events": []})
    from routers.teams import agents as agents_mod

    monkeypatch.setattr(agents_mod, "_admin", lambda: admin)

    r = client.get(
        "/api/v1/teams/activity",
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 200
    admin.list_activity.assert_awaited_once_with(
        company_id="co_abc",
        session_cookie="cookie",
    )


def test_get_costs(client, monkeypatch):
    admin = MagicMock()
    admin.get_costs = AsyncMock(return_value={"total": 0})
    from routers.teams import agents as agents_mod

    monkeypatch.setattr(agents_mod, "_admin", lambda: admin)

    r = client.get(
        "/api/v1/teams/costs",
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 200
    admin.get_costs.assert_awaited_once_with(
        company_id="co_abc",
        session_cookie="cookie",
    )


def test_get_dashboard_aggregates_dash_and_badges(client, monkeypatch):
    """Dashboard endpoint must call both ``get_dashboard`` and
    ``get_sidebar_badges`` in parallel, flatten the dashboard payload
    into the scalar shape DashboardPanel expects, and pass through
    sidebar_badges verbatim."""
    admin = MagicMock()
    admin.get_dashboard = AsyncMock(
        return_value={
            "companyId": "co_abc",
            "agents": {"active": 2, "running": 1, "paused": 4, "error": 1},
            "tasks": {"open": 5, "inProgress": 2, "blocked": 1, "done": 7},
            "costs": {
                "monthSpendCents": 12345,
                "monthBudgetCents": 50000,
                "monthUtilizationPercent": 24.69,
            },
            "runActivity": [
                {"date": "2026-04-19", "total": 3},
                {"date": "2026-05-02", "total": 8},
            ],
        }
    )
    admin.get_sidebar_badges = AsyncMock(return_value={"inbox": 3})
    from routers.teams import agents as agents_mod

    monkeypatch.setattr(agents_mod, "_admin", lambda: admin)

    r = client.get(
        "/api/v1/teams/dashboard",
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "dashboard": {
            "agents": 8,  # all status buckets summed: 2+1+4+1
            "openIssues": 5,
            "runsToday": 8,
            "spendCents": 12345,
        },
        "sidebar_badges": {"inbox": 3},
    }
    admin.get_dashboard.assert_awaited_once_with(
        company_id="co_abc",
        session_cookie="cookie",
    )
    admin.get_sidebar_badges.assert_awaited_once_with(
        company_id="co_abc",
        session_cookie="cookie",
    )


def test_get_dashboard_handles_missing_subfields(client, monkeypatch):
    """If upstream ever returns null/missing sub-fields, the BFF must
    coerce to 0 rather than 500 — DashboardPanel renders the result as
    JSX values, so any non-scalar leaks back as a React crash."""
    admin = MagicMock()
    admin.get_dashboard = AsyncMock(return_value={})
    admin.get_sidebar_badges = AsyncMock(return_value={})
    from routers.teams import agents as agents_mod

    monkeypatch.setattr(agents_mod, "_admin", lambda: admin)

    r = client.get(
        "/api/v1/teams/dashboard",
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 200
    assert r.json()["dashboard"] == {
        "agents": 0,
        "openIssues": 0,
        "runsToday": 0,
        "spendCents": 0,
    }


def test_get_sidebar_badges(client, monkeypatch):
    admin = MagicMock()
    admin.get_sidebar_badges = AsyncMock(return_value={"inbox": 2})
    from routers.teams import agents as agents_mod

    monkeypatch.setattr(agents_mod, "_admin", lambda: admin)

    r = client.get(
        "/api/v1/teams/sidebar-badges",
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 200
    admin.get_sidebar_badges.assert_awaited_once_with(
        company_id="co_abc",
        session_cookie="cookie",
    )
