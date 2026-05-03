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
