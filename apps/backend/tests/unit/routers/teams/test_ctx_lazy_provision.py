"""Tests for the BFF ``_ctx`` Depends helper's lazy-provision branch.

When a personal-context user hits ``/teams/*`` and they have no DDB row in
``paperclip-companies``, the BFF should:

  - Check that they have an active container (paywall proxy, since
    ``/container/provision`` requires an active subscription).
  - If yes: fire ``ensure_paperclip_workspace`` as a background task and
    raise 202 so the frontend polls.
  - If no: raise 402 (subscribe first).

Org context keeps the original 409 — those rows are owned by the Clerk
``organization.created`` webhook and a missing row signals an operator
issue, not a self-heal opportunity.
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")


def _auth(user_id: str = "u1", org_id: str | None = None, is_org_context: bool = False) -> MagicMock:
    auth = MagicMock()
    auth.user_id = user_id
    auth.org_id = org_id
    auth.is_org_context = is_org_context
    return auth


@pytest.mark.asyncio
async def test_ctx_returns_context_when_resolve_succeeds():
    """Happy path — resolve_teams_context returned a context, _ctx
    passes it through unchanged without touching container_repo or
    asyncio.create_task."""
    from routers.teams import agents as agents_mod
    from routers.teams.deps import TeamsContext

    fake_ctx = TeamsContext(
        user_id="u1",
        org_id=None,
        owner_id="u1",
        company_id="co_abc",
        paperclip_user_id="pcu_xyz",
        session_cookie="cookie",
    )

    with (
        patch.object(
            agents_mod.deps_mod,
            "resolve_teams_context",
            new_callable=AsyncMock,
            return_value=fake_ctx,
        ),
        patch.object(
            agents_mod.container_repo,
            "get_by_owner_id",
            new_callable=AsyncMock,
        ) as container_mock,
        patch.object(agents_mod, "ensure_paperclip_workspace", new_callable=AsyncMock) as ensure_mock,
    ):
        result = await agents_mod._ctx(auth=_auth())

    assert result is fake_ctx
    container_mock.assert_not_awaited()
    ensure_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_ctx_lazy_provisions_when_personal_user_has_container():
    """Missing row + personal + container exists -> bg task + 202."""
    from routers.teams import agents as agents_mod
    from routers.teams.deps import TeamsContextError

    raise_409 = TeamsContextError(status_code=409, detail="team workspace not provisioned")

    with (
        patch.object(
            agents_mod.deps_mod,
            "resolve_teams_context",
            new_callable=AsyncMock,
            side_effect=raise_409,
        ),
        patch.object(
            agents_mod.container_repo,
            "get_by_owner_id",
            new_callable=AsyncMock,
            return_value={"status": "running", "service_name": "openclaw-x"},
        ),
        patch.object(agents_mod, "ensure_paperclip_workspace", new_callable=AsyncMock) as ensure_mock,
    ):
        with pytest.raises(TeamsContextError) as exc:
            await agents_mod._ctx(auth=_auth())
        # asyncio.create_task is scheduled but not yet run — yield once
        # so the loop picks up the AsyncMock.
        await asyncio.sleep(0)

    assert exc.value.status_code == 202
    assert exc.value.detail == "team workspace provisioning"
    ensure_mock.assert_awaited_once_with(owner_id="u1", clerk_user_id="u1")


@pytest.mark.asyncio
async def test_ctx_returns_402_when_personal_user_has_no_container():
    """Missing row + personal + no container -> 402 subscribe-first."""
    from routers.teams import agents as agents_mod
    from routers.teams.deps import TeamsContextError

    raise_409 = TeamsContextError(status_code=409, detail="team workspace not provisioned")

    with (
        patch.object(
            agents_mod.deps_mod,
            "resolve_teams_context",
            new_callable=AsyncMock,
            side_effect=raise_409,
        ),
        patch.object(
            agents_mod.container_repo,
            "get_by_owner_id",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch.object(agents_mod, "ensure_paperclip_workspace", new_callable=AsyncMock) as ensure_mock,
    ):
        with pytest.raises(TeamsContextError) as exc:
            await agents_mod._ctx(auth=_auth())

    assert exc.value.status_code == 402
    ensure_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_ctx_propagates_409_for_org_context():
    """Org context: missing row stays 409. The Clerk webhook owns
    org provisioning; lazy-self-heal here would race with it and create
    a personal-shaped row for an org owner."""
    from routers.teams import agents as agents_mod
    from routers.teams.deps import TeamsContextError

    raise_409 = TeamsContextError(status_code=409, detail="team workspace not provisioned")

    with (
        patch.object(
            agents_mod.deps_mod,
            "resolve_teams_context",
            new_callable=AsyncMock,
            side_effect=raise_409,
        ),
        patch.object(
            agents_mod.container_repo,
            "get_by_owner_id",
            new_callable=AsyncMock,
        ) as container_mock,
        patch.object(agents_mod, "ensure_paperclip_workspace", new_callable=AsyncMock) as ensure_mock,
    ):
        with pytest.raises(TeamsContextError) as exc:
            await agents_mod._ctx(auth=_auth(org_id="org_x", is_org_context=True))

    assert exc.value.status_code == 409
    container_mock.assert_not_awaited()
    ensure_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_ctx_propagates_other_status_codes_unchanged():
    """A 503 (failed) or 202 (already provisioning) from
    resolve_teams_context must propagate unchanged — only the specific
    'not provisioned' 409 triggers the lazy path."""
    from routers.teams import agents as agents_mod
    from routers.teams.deps import TeamsContextError

    raise_503 = TeamsContextError(status_code=503, detail="team workspace provisioning failed")

    with (
        patch.object(
            agents_mod.deps_mod,
            "resolve_teams_context",
            new_callable=AsyncMock,
            side_effect=raise_503,
        ),
        patch.object(
            agents_mod.container_repo,
            "get_by_owner_id",
            new_callable=AsyncMock,
        ) as container_mock,
        patch.object(agents_mod, "ensure_paperclip_workspace", new_callable=AsyncMock) as ensure_mock,
    ):
        with pytest.raises(TeamsContextError) as exc:
            await agents_mod._ctx(auth=_auth())

    assert exc.value.status_code == 503
    container_mock.assert_not_awaited()
    ensure_mock.assert_not_awaited()
