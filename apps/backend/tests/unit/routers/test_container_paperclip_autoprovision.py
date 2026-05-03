"""Tests for the Paperclip auto-provision hook in /container.

Personal-context users have no Clerk org, so the
``organization.created`` webhook never fires for them. Without an
auto-provision hook here, their /teams UI 404s on first visit until
they manually re-trigger provisioning. These tests pin down the
contract:

  - Personal context (owner_id == clerk_user_id): we resolve the
    owner's email and call ``provision_org``.
  - Org context (owner_id != clerk_user_id): we skip — the Clerk
    ``organization.created`` webhook in routers/webhooks.py owns it.
  - Missing email: we log and skip rather than crashing.
  - provision_org failure: we swallow the exception so a flaky
    Paperclip never breaks container provisioning.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")


@pytest.mark.asyncio
async def test_ensure_paperclip_personal_calls_provision_org():
    """Personal context: resolve email, build provisioning, call provision_org."""
    from routers.container import _ensure_paperclip_workspace

    fake_provisioning = MagicMock()
    fake_provisioning.provision_org = AsyncMock(return_value=MagicMock())

    with (
        patch(
            "core.services.paperclip_owner_email.lookup_owner_email",
            new_callable=AsyncMock,
            return_value="user@example.com",
        ),
        patch(
            "routers.webhooks._get_paperclip_provisioning",
            new_callable=AsyncMock,
            return_value=fake_provisioning,
        ),
        patch(
            "routers.webhooks._close_paperclip_http",
            new_callable=AsyncMock,
        ) as close_mock,
    ):
        await _ensure_paperclip_workspace(owner_id="user_abc", clerk_user_id="user_abc")

    fake_provisioning.provision_org.assert_awaited_once_with(
        org_id="user_abc",
        owner_user_id="user_abc",
        owner_email="user@example.com",
    )
    close_mock.assert_awaited_once_with(fake_provisioning)


@pytest.mark.asyncio
async def test_ensure_paperclip_org_context_skips():
    """Org context: skip — Clerk org webhook handles it."""
    from routers.container import _ensure_paperclip_workspace

    with (
        patch(
            "routers.webhooks._get_paperclip_provisioning",
            new_callable=AsyncMock,
        ) as get_mock,
    ):
        await _ensure_paperclip_workspace(owner_id="org_xyz", clerk_user_id="user_abc")

    get_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_ensure_paperclip_missing_email_skips():
    """No email -> log + skip; do not call provision_org."""
    from routers.container import _ensure_paperclip_workspace

    fake_provisioning = MagicMock()
    fake_provisioning.provision_org = AsyncMock()

    with (
        patch(
            "core.services.paperclip_owner_email.lookup_owner_email",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "routers.webhooks._get_paperclip_provisioning",
            new_callable=AsyncMock,
            return_value=fake_provisioning,
        ),
    ):
        await _ensure_paperclip_workspace(owner_id="user_abc", clerk_user_id="user_abc")

    fake_provisioning.provision_org.assert_not_awaited()


@pytest.mark.asyncio
async def test_ensure_paperclip_provision_failure_is_swallowed():
    """provision_org throwing must NOT propagate — Paperclip outage
    cannot break container provisioning. User can retry from /teams."""
    from routers.container import _ensure_paperclip_workspace

    fake_provisioning = MagicMock()
    fake_provisioning.provision_org = AsyncMock(side_effect=RuntimeError("paperclip down"))

    with (
        patch(
            "core.services.paperclip_owner_email.lookup_owner_email",
            new_callable=AsyncMock,
            return_value="user@example.com",
        ),
        patch(
            "routers.webhooks._get_paperclip_provisioning",
            new_callable=AsyncMock,
            return_value=fake_provisioning,
        ),
        patch(
            "routers.webhooks._close_paperclip_http",
            new_callable=AsyncMock,
        ),
    ):
        # Must not raise.
        await _ensure_paperclip_workspace(owner_id="user_abc", clerk_user_id="user_abc")


@pytest.mark.asyncio
async def test_background_provision_calls_paperclip_after_container_succeeds():
    """The auto-retry path (_background_provision) must hook Paperclip too,
    not just POST /provision and POST /retry."""
    from routers.container import _background_provision

    fake_ecs = MagicMock()
    fake_ecs.provision_user_container = AsyncMock(return_value="openclaw-foo")

    with (
        patch("routers.container.get_ecs_manager", return_value=fake_ecs),
        patch(
            "routers.container.user_repo.get",
            new_callable=AsyncMock,
            return_value={"provider_choice": "bedrock_claude"},
        ),
        patch(
            "routers.container._ensure_paperclip_workspace",
            new_callable=AsyncMock,
        ) as ensure_mock,
    ):
        await _background_provision("user_abc", "user_abc")

    fake_ecs.provision_user_container.assert_awaited_once()
    ensure_mock.assert_awaited_once_with(owner_id="user_abc", clerk_user_id="user_abc")


@pytest.mark.asyncio
async def test_background_provision_skips_paperclip_when_container_fails():
    """If the container itself fails to provision, don't try Paperclip —
    the user has bigger problems and the retry path will hit Paperclip
    on the next successful provision."""
    from routers.container import _background_provision

    fake_ecs = MagicMock()
    fake_ecs.provision_user_container = AsyncMock(side_effect=RuntimeError("ecs blew up"))

    with (
        patch("routers.container.get_ecs_manager", return_value=fake_ecs),
        patch(
            "routers.container.user_repo.get",
            new_callable=AsyncMock,
            return_value={"provider_choice": "bedrock_claude"},
        ),
        patch(
            "routers.container._ensure_paperclip_workspace",
            new_callable=AsyncMock,
        ) as ensure_mock,
    ):
        await _background_provision("user_abc", "user_abc")

    ensure_mock.assert_not_awaited()
