"""Tests for backend lifespan startup/shutdown wiring."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_resume_provisioning_transitions_kicks_off_poller_per_row():
    """After a backend restart any container still in status=provisioning in
    DDB MUST have its transition poller resumed. Without this, a deploy that
    lands mid-provision permanently strands the container at status=provisioning
    because the original asyncio task was killed on shutdown."""
    from main import _resume_provisioning_transitions

    provisioning_rows = [
        {"owner_id": "user_a", "status": "provisioning"},
        {"owner_id": "user_b", "status": "provisioning"},
    ]

    mock_ecs = MagicMock()
    mock_ecs._await_running_transition = AsyncMock()

    with (
        patch(
            "main.container_repo.get_by_status",
            new_callable=AsyncMock,
            return_value=provisioning_rows,
        ) as mock_get,
        patch("main.get_ecs_manager", return_value=mock_ecs),
    ):
        await _resume_provisioning_transitions()

        # Give fire-and-forget tasks a chance to be scheduled and awaited.
        import asyncio as _asyncio

        await _asyncio.sleep(0)

        mock_get.assert_awaited_once_with("provisioning")
        assert mock_ecs._await_running_transition.await_count == 2
        awaited_users = {call.args[0] for call in mock_ecs._await_running_transition.await_args_list}
        assert awaited_users == {"user_a", "user_b"}


@pytest.mark.asyncio
async def test_resume_provisioning_transitions_tolerates_empty():
    """Zero provisioning rows -> no-op, no error."""
    from main import _resume_provisioning_transitions

    mock_ecs = MagicMock()
    mock_ecs._await_running_transition = AsyncMock()

    with (
        patch(
            "main.container_repo.get_by_status",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch("main.get_ecs_manager", return_value=mock_ecs),
    ):
        await _resume_provisioning_transitions()

        mock_ecs._await_running_transition.assert_not_called()


@pytest.mark.asyncio
async def test_resume_provisioning_transitions_tolerates_ddb_failure():
    """get_by_status raising MUST NOT crash backend startup -- reconciliation
    is best-effort; a transient DDB error should be logged and shrug off."""
    from main import _resume_provisioning_transitions

    with (
        patch(
            "main.container_repo.get_by_status",
            new_callable=AsyncMock,
            side_effect=RuntimeError("ddb transient"),
        ),
        patch("main.get_ecs_manager") as mock_get_ecs,
    ):
        # Must not raise.
        await _resume_provisioning_transitions()

        mock_get_ecs.assert_not_called()
