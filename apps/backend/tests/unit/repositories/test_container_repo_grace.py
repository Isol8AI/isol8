"""Tests for container_repo grace-window helpers."""

import time
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_set_reconciler_grace_writes_epoch_seconds():
    from core.repositories import container_repo

    with (
        patch.object(
            container_repo, "get_by_owner_id", AsyncMock(return_value={"owner_id": "u1", "id": "i", "created_at": "x"})
        ),
        patch.object(container_repo, "update_fields", AsyncMock(return_value={})) as mock_update,
    ):
        before = int(time.time())
        await container_repo.set_reconciler_grace("u1", seconds=5)
        after = int(time.time())

    mock_update.assert_awaited_once()
    args, _ = mock_update.call_args
    owner_id, fields = args
    assert owner_id == "u1"
    assert "reconciler_grace_until" in fields
    assert before + 5 <= fields["reconciler_grace_until"] <= after + 6


@pytest.mark.asyncio
async def test_get_reconciler_grace_returns_zero_when_unset():
    from core.repositories import container_repo

    with patch.object(container_repo, "get_by_owner_id", AsyncMock(return_value={"owner_id": "u1"})):
        grace = await container_repo.get_reconciler_grace("u1")
    assert grace == 0


@pytest.mark.asyncio
async def test_get_reconciler_grace_returns_stored_value():
    from core.repositories import container_repo

    with patch.object(
        container_repo,
        "get_by_owner_id",
        AsyncMock(return_value={"owner_id": "u1", "reconciler_grace_until": 1234567890}),
    ):
        grace = await container_repo.get_reconciler_grace("u1")
    assert grace == 1234567890
