"""Tests for admin_service org-aware owner_id resolution.

Background: the DDB partition key ``owner_id`` equals Clerk ``org_id`` for
org-member resources and ``user_id`` for personal-mode resources. The admin
dashboard receives the target user_id from the URL, so it must resolve the
effective owner_id via Clerk before querying container_repo / billing_repo /
usage_repo — otherwise org-member users render as "no container provisioned".

These tests pin:
- get_overview queries DDB with org_id (not user_id) when Clerk reports org
  membership, and returns org_context in the ``org`` response field.
- get_overview falls back to user_id when Clerk reports no orgs, and returns
  ``org: None``.
- get_overview is defensive: when Clerk itself errors, we still render the
  personal-mode payload (fail-open) rather than 500 the whole dashboard.
"""

import os
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")


@pytest.mark.asyncio
async def test_get_overview_uses_org_id_as_owner_when_user_is_in_org():
    """User in an org → repos queried with org_id, response includes org."""
    from core.services import admin_service

    org = {
        "id": "org_abc",
        "slug": "acme",
        "name": "Acme Co.",
        "role": "org:admin",
    }

    with (
        patch(
            "core.services.admin_service.clerk_admin.list_user_organizations",
            new=AsyncMock(return_value=[org]),
        ),
        patch(
            "core.services.admin_service.clerk_admin.get_user",
            new=AsyncMock(return_value={"id": "user_abc", "email_addresses": []}),
        ),
        patch(
            "core.services.admin_service.container_repo.get_by_owner_id",
            new=AsyncMock(return_value={"status": "running", "plan_tier": "pro"}),
        ) as mock_container,
        patch(
            "core.services.admin_service.billing_repo.get_by_owner_id",
            new=AsyncMock(return_value={"plan_tier": "pro"}),
        ) as mock_billing,
        patch(
            "core.services.admin_service.usage_repo.get_period_usage",
            new=AsyncMock(return_value={"total_spend_microdollars": 0}),
        ) as mock_usage,
    ):
        result = await admin_service.get_overview("user_abc")

    # Repos must be queried with the ORG id, not the USER id.
    mock_container.assert_awaited_once_with("org_abc")
    mock_billing.assert_awaited_once_with("org_abc")
    # usage_repo.get_period_usage takes (owner_id, period)
    assert mock_usage.await_args.args[0] == "org_abc"

    # Response carries org context.
    assert result["org"] == org
    assert result["identity"]["id"] == "user_abc"
    assert result["container"]["status"] == "running"


@pytest.mark.asyncio
async def test_get_overview_uses_user_id_when_personal_mode():
    """User in no orgs → repos queried with user_id, ``org`` is None."""
    from core.services import admin_service

    with (
        patch(
            "core.services.admin_service.clerk_admin.list_user_organizations",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "core.services.admin_service.clerk_admin.get_user",
            new=AsyncMock(return_value={"id": "user_solo"}),
        ),
        patch(
            "core.services.admin_service.container_repo.get_by_owner_id",
            new=AsyncMock(return_value={"status": "running"}),
        ) as mock_container,
        patch(
            "core.services.admin_service.billing_repo.get_by_owner_id",
            new=AsyncMock(return_value=None),
        ) as mock_billing,
        patch(
            "core.services.admin_service.usage_repo.get_period_usage",
            new=AsyncMock(return_value={}),
        ) as mock_usage,
    ):
        result = await admin_service.get_overview("user_solo")

    mock_container.assert_awaited_once_with("user_solo")
    mock_billing.assert_awaited_once_with("user_solo")
    assert mock_usage.await_args.args[0] == "user_solo"

    assert result["org"] is None


@pytest.mark.asyncio
async def test_get_overview_falls_back_to_user_id_when_clerk_errors():
    """Clerk org lookup raising must NOT 500 the dashboard — fall back to
    personal-mode lookup so the admin can still see something."""
    from core.services import admin_service

    async def raising_clerk(user_id: str):  # noqa: ARG001
        raise RuntimeError("clerk 503")

    with (
        patch(
            "core.services.admin_service.clerk_admin.list_user_organizations",
            side_effect=raising_clerk,
        ),
        patch(
            "core.services.admin_service.clerk_admin.get_user",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "core.services.admin_service.container_repo.get_by_owner_id",
            new=AsyncMock(return_value=None),
        ) as mock_container,
        patch(
            "core.services.admin_service.billing_repo.get_by_owner_id",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "core.services.admin_service.usage_repo.get_period_usage",
            new=AsyncMock(return_value={}),
        ),
    ):
        result = await admin_service.get_overview("user_flaky")

    mock_container.assert_awaited_once_with("user_flaky")
    assert result["org"] is None


@pytest.mark.asyncio
async def test_get_overview_picks_first_org_when_clerk_returns_multiple():
    """project_single_org_per_user: one org per user. If Clerk returns
    multiple (shouldn't happen) we use the first and log a warning."""
    from core.services import admin_service

    orgs = [
        {"id": "org_first", "slug": "first", "name": "First", "role": "org:admin"},
        {"id": "org_second", "slug": "second", "name": "Second", "role": "org:member"},
    ]

    with (
        patch(
            "core.services.admin_service.clerk_admin.list_user_organizations",
            new=AsyncMock(return_value=orgs),
        ),
        patch(
            "core.services.admin_service.clerk_admin.get_user",
            new=AsyncMock(return_value={"id": "user_multi"}),
        ),
        patch(
            "core.services.admin_service.container_repo.get_by_owner_id",
            new=AsyncMock(return_value=None),
        ) as mock_container,
        patch(
            "core.services.admin_service.billing_repo.get_by_owner_id",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "core.services.admin_service.usage_repo.get_period_usage",
            new=AsyncMock(return_value={}),
        ),
    ):
        result = await admin_service.get_overview("user_multi")

    mock_container.assert_awaited_once_with("org_first")
    assert result["org"]["id"] == "org_first"


@pytest.mark.asyncio
async def test_list_user_agents_uses_org_id_for_container_lookup():
    """Agents-list container lookup must hit org_id when user is in an org."""
    from core.services import admin_service

    org = {"id": "org_abc", "slug": "acme", "name": "Acme", "role": "org:admin"}

    with (
        patch(
            "core.services.admin_service.clerk_admin.list_user_organizations",
            new=AsyncMock(return_value=[org]),
        ),
        patch(
            "core.services.admin_service.container_repo.get_by_owner_id",
            new=AsyncMock(return_value=None),
        ) as mock_container,
    ):
        result = await admin_service.list_user_agents("user_abc")

    mock_container.assert_awaited_once_with("org_abc")
    assert result["org"] == org
    assert result["container_status"] == "none"


@pytest.mark.asyncio
async def test_get_agent_detail_uses_org_id_for_container_lookup():
    """Agent detail container lookup must hit org_id when user is in an org."""
    from core.services import admin_service

    org = {"id": "org_abc", "slug": "acme", "name": "Acme", "role": "org:admin"}

    with (
        patch(
            "core.services.admin_service.clerk_admin.list_user_organizations",
            new=AsyncMock(return_value=[org]),
        ),
        patch(
            "core.services.admin_service.container_repo.get_by_owner_id",
            new=AsyncMock(return_value={"status": "stopped"}),
        ) as mock_container,
    ):
        result = await admin_service.get_agent_detail("user_abc", "agt_1")

    mock_container.assert_awaited_once_with("org_abc")
    assert result["error"] == "container_not_running"
    assert result["org"] == org
