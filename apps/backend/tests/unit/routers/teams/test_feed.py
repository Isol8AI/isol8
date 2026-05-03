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
    ``get_sidebar_badges`` and return both under a stable shape."""
    admin = MagicMock()
    admin.get_dashboard = AsyncMock(return_value={"x": 1})
    admin.get_sidebar_badges = AsyncMock(return_value={"inbox": 3})
    from routers.teams import agents as agents_mod

    monkeypatch.setattr(agents_mod, "_admin", lambda: admin)

    r = client.get(
        "/api/v1/teams/dashboard",
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body == {"dashboard": {"x": 1}, "sidebar_badges": {"inbox": 3}}
    admin.get_dashboard.assert_awaited_once_with(
        company_id="co_abc",
        session_cookie="cookie",
    )
    admin.get_sidebar_badges.assert_awaited_once_with(
        company_id="co_abc",
        session_cookie="cookie",
    )


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
