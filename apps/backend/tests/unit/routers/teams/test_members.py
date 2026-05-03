"""Tests for the Teams Members BFF (Task 12).

Members endpoint joins Paperclip ``companyMemberships`` with Clerk
user info via ``_resolve_user_email`` (re-exported from
``routers.teams.agents``).
"""

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


def test_list_members_joins_clerk_email(client, monkeypatch):
    """Each upstream member row should be enriched with
    ``email_via_clerk`` resolved through ``_resolve_user_email``."""
    admin = MagicMock()
    admin.list_members = AsyncMock(
        return_value={
            "members": [
                {"id": "m1", "principalId": "user_aaa", "role": "owner"},
                {"id": "m2", "principalId": "user_bbb", "role": "member"},
            ]
        }
    )

    async def fake_resolve(user_id: str) -> str:
        return f"{user_id}@example.com"

    from routers.teams import agents as agents_mod

    monkeypatch.setattr(agents_mod, "_admin", lambda: admin)
    monkeypatch.setattr(agents_mod, "_resolve_user_email", fake_resolve)

    r = client.get(
        "/api/v1/teams/members",
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "members": [
            {
                "id": "m1",
                "principalId": "user_aaa",
                "role": "owner",
                "email_via_clerk": "user_aaa@example.com",
            },
            {
                "id": "m2",
                "principalId": "user_bbb",
                "role": "member",
                "email_via_clerk": "user_bbb@example.com",
            },
        ]
    }
    admin.list_members.assert_awaited_once_with(
        company_id="co_abc",
        session_cookie="cookie",
    )


def test_list_members_tolerates_clerk_failure(client, monkeypatch):
    """If Clerk lookup raises, the member row still ships with
    ``email_via_clerk: None`` instead of failing the whole request."""
    admin = MagicMock()
    admin.list_members = AsyncMock(return_value={"members": [{"id": "m1", "principalId": "user_aaa"}]})

    async def fake_resolve(user_id: str) -> str:
        raise RuntimeError("clerk down")

    from routers.teams import agents as agents_mod

    monkeypatch.setattr(agents_mod, "_admin", lambda: admin)
    monkeypatch.setattr(agents_mod, "_resolve_user_email", fake_resolve)

    r = client.get(
        "/api/v1/teams/members",
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "members": [
            {
                "id": "m1",
                "principalId": "user_aaa",
                "email_via_clerk": None,
            }
        ]
    }
