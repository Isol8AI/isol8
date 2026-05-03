"""Tests for the Teams Approvals BFF (Task 8).

Audit §3: ``payload.adapterType`` is an indirect smuggling carrier;
the body whitelist on ``ApproveApprovalBody`` / ``RejectApprovalBody``
must reject any non-whitelisted field with 422.
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


def test_list_approvals_proxies_with_session(client, monkeypatch):
    admin = MagicMock()
    admin.list_approvals = AsyncMock(return_value={"approvals": []})
    from routers.teams import agents as agents_mod

    monkeypatch.setattr(agents_mod, "_admin", lambda: admin)

    r = client.get(
        "/api/v1/teams/approvals",
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 200
    admin.list_approvals.assert_awaited_once_with(
        company_id="co_abc",
        session_cookie="cookie",
    )


def test_approve_with_note(client, monkeypatch):
    admin = MagicMock()
    admin.approve_approval = AsyncMock(return_value={"ok": True})
    from routers.teams import agents as agents_mod

    monkeypatch.setattr(agents_mod, "_admin", lambda: admin)

    r = client.post(
        "/api/v1/teams/approvals/ap_1/approve",
        json={"note": "lgtm"},
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 200
    admin.approve_approval.assert_awaited_once_with(
        approval_id="ap_1",
        note="lgtm",
        session_cookie="cookie",
    )


def test_approve_rejects_smuggled_adapter_type(client):
    """A client attempting to smuggle ``adapterType`` through the
    approval payload must be rejected with 422 — body schema forbids
    extras."""
    r = client.post(
        "/api/v1/teams/approvals/ap_1/approve",
        json={"note": "lgtm", "adapterType": "process"},
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 422


def test_reject_requires_reason(client):
    """``reason`` is required by ``RejectApprovalBody``; missing it must 422."""
    r = client.post(
        "/api/v1/teams/approvals/ap_1/reject",
        json={},
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 422
