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
    admin = MagicMock()
    admin.list_inbox = AsyncMock(return_value={"items": []})
    # Patch the shared singleton on agents — inbox.py imports the same name.
    from routers.teams import agents as agents_mod

    monkeypatch.setattr(agents_mod, "_admin", lambda: admin)

    r = client.get("/api/v1/teams/inbox", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    assert r.json() == {"items": []}
    admin.list_inbox.assert_awaited_once_with(
        company_id="co_abc",
        session_cookie="cookie",
    )


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
