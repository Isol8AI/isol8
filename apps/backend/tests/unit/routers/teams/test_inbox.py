"""Tests for the Teams Inbox BFF (Task 7)."""

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
    """Bypass the auth/session chain by overriding the shared ``_ctx`` dep."""
    from routers.teams import agents as agents_mod

    async def fake_ctx():
        return teams_ctx

    app.dependency_overrides[agents_mod._ctx] = fake_ctx
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(agents_mod._ctx, None)


def test_list_inbox_proxies_with_session(client, monkeypatch):
    """The BFF must call ``/api/agents/me/inbox-lite`` (NOT the
    invented ``/api/companies/{co}/inbox`` which doesn't exist in
    Paperclip) and reshape the upstream issue array into the
    ``{items: [...]}`` envelope the InboxPanel expects."""
    admin = MagicMock()
    admin.list_inbox_for_session_user = AsyncMock(return_value=[])
    # Patch the shared singleton on agents — inbox.py imports the same name.
    from routers.teams import agents as agents_mod

    monkeypatch.setattr(agents_mod, "_admin", lambda: admin)

    r = client.get("/api/v1/teams/inbox", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    assert r.json() == {"items": []}
    admin.list_inbox_for_session_user.assert_awaited_once_with(
        session_cookie="cookie",
    )


def test_list_inbox_reshapes_issue_rows(client, monkeypatch):
    """Confirm the BFF maps Paperclip's inbox-lite issue array into the
    InboxPanel's ``{items: [{id, type, title, createdAt}]}`` shape."""
    admin = MagicMock()
    admin.list_inbox_for_session_user = AsyncMock(
        return_value=[
            {
                "id": "iss_1",
                "identifier": "PAP-1",
                "title": "Fix the inbox",
                "status": "todo",
                "priority": "high",
                "updatedAt": "2026-05-02T00:00:00Z",
            },
            {
                "id": "iss_2",
                "identifier": "PAP-2",
                "title": "Ship it",
                "status": "in_progress",
                "updatedAt": "2026-05-02T01:00:00Z",
            },
        ]
    )
    from routers.teams import agents as agents_mod

    monkeypatch.setattr(agents_mod, "_admin", lambda: admin)

    r = client.get("/api/v1/teams/inbox", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "items": [
            {
                "id": "iss_1",
                "type": "todo",
                "title": "Fix the inbox",
                "createdAt": "2026-05-02T00:00:00Z",
            },
            {
                "id": "iss_2",
                "type": "in_progress",
                "title": "Ship it",
                "createdAt": "2026-05-02T01:00:00Z",
            },
        ]
    }


def test_dismiss_proxies_with_session(client, monkeypatch):
    admin = MagicMock()
    admin.dismiss_inbox_item = AsyncMock(return_value={"ok": True})
    from routers.teams import agents as agents_mod

    monkeypatch.setattr(agents_mod, "_admin", lambda: admin)

    r = client.post(
        "/api/v1/teams/inbox/itm_1/dismiss",
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 200
    admin.dismiss_inbox_item.assert_awaited_once_with(
        item_id="itm_1",
        session_cookie="cookie",
    )


def test_list_inbox_forwards_filter_params(client, monkeypatch):
    """The expanded /inbox accepts query params (tab, status, project,
    assignee, creator, search, limit) and forwards them verbatim to the
    upstream inbox-lite endpoint."""
    admin = MagicMock()
    admin.list_inbox_for_session_user = AsyncMock(return_value=[])
    from routers.teams import agents as agents_mod

    monkeypatch.setattr(agents_mod, "_admin", lambda: admin)

    r = client.get(
        "/api/v1/teams/inbox",
        params={
            "tab": "mine",
            "status": "todo",
            "project": "proj_1",
            "assignee": "agent_2",
            "creator": "user_3",
            "search": "fix bug",
            "limit": 250,
        },
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 200
    admin.list_inbox_for_session_user.assert_awaited_once()
    call = admin.list_inbox_for_session_user.call_args
    assert call.kwargs["session_cookie"] == "cookie"
    assert call.kwargs["params"] == {
        "tab": "mine",
        "status": "todo",
        "project": "proj_1",
        "assignee": "agent_2",
        "creator": "user_3",
        "search": "fix bug",
        "limit": "250",
    }


def test_list_inbox_omits_unset_filter_params(client, monkeypatch):
    """Filter params that are not provided must NOT be forwarded as
    empty strings to upstream — empty params dict (or None) instead."""
    admin = MagicMock()
    admin.list_inbox_for_session_user = AsyncMock(return_value=[])
    from routers.teams import agents as agents_mod

    monkeypatch.setattr(agents_mod, "_admin", lambda: admin)

    r = client.get("/api/v1/teams/inbox", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    call = admin.list_inbox_for_session_user.call_args
    # Lock the back-compat contract: when no filters are set, the BFF
    # MUST omit the params kwarg entirely. test_list_inbox_proxies_with_session
    # asserts the kwargs shape `{session_cookie: "cookie"}` — passing
    # params=None or params={} would break that assertion.
    assert "params" not in call.kwargs


def test_list_inbox_runs_returns_failed_runs(client, monkeypatch):
    """`GET /teams/inbox/runs` lists failed heartbeat runs (the ones the
    Inbox 'Runs' tab needs)."""
    admin = MagicMock()
    admin.list_company_heartbeat_runs = AsyncMock(return_value={"runs": [{"id": "run_1", "status": "failed"}]})
    from routers.teams import agents as agents_mod

    monkeypatch.setattr(agents_mod, "_admin", lambda: admin)

    r = client.get("/api/v1/teams/inbox/runs", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    assert r.json() == {"runs": [{"id": "run_1", "status": "failed"}]}
    admin.list_company_heartbeat_runs.assert_awaited_once_with(
        company_id="co_abc",
        session_cookie="cookie",
        status="failed",
    )


def test_list_inbox_live_runs(client, monkeypatch):
    """`GET /teams/inbox/live-runs` returns currently-running runs for the
    'Live' badge on Inbox rows."""
    admin = MagicMock()
    admin.list_company_live_runs = AsyncMock(return_value={"runs": [{"id": "run_live"}]})
    from routers.teams import agents as agents_mod

    monkeypatch.setattr(agents_mod, "_admin", lambda: admin)

    r = client.get(
        "/api/v1/teams/inbox/live-runs",
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 200
    admin.list_company_live_runs.assert_awaited_once_with(
        company_id="co_abc",
        session_cookie="cookie",
    )


@pytest.mark.parametrize("tab", ["mine", "recent", "all", "unread", "approvals", "runs", "joins"])
def test_list_inbox_accepts_all_documented_tabs(client, monkeypatch, tab):
    """Codex P1 on PR #524: the tab regex must accept the full set of
    upstream Inbox tabs, not just the 4 work-item tabs. The Paperclip
    Inbox UI also uses approvals/runs/joins as tab values that route
    through this same endpoint; rejecting them at the BFF blocks the
    Approvals/Runs/Joins tabs from ever loading."""
    admin = MagicMock()
    admin.list_inbox_for_session_user = AsyncMock(return_value=[])
    from routers.teams import agents as agents_mod

    monkeypatch.setattr(agents_mod, "_admin", lambda: admin)

    r = client.get(
        "/api/v1/teams/inbox",
        params={"tab": tab},
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 200, f"tab={tab} was rejected: {r.json()}"


def test_list_inbox_rejects_unknown_tab(client):
    """Sanity check: the regex still rejects nonsense to keep the
    forwarded query string within the documented vocabulary."""
    r = client.get(
        "/api/v1/teams/inbox",
        params={"tab": "evil-tab"},
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 422
