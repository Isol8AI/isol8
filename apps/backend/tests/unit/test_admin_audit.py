"""Unit tests for @audit_admin_action decorator.

Verifies:
1. New `target_user_id_override` kwarg sets the audit row's target
   to the override value verbatim (used for catalog actions that
   target the shared catalog, not a specific user).
2. Existing kwarg-based target resolution is preserved when no
   override is given.
"""

from unittest.mock import AsyncMock, patch

import pytest

from core.auth import AuthContext
from core.services.admin_audit import audit_admin_action


class _Req:
    """Minimal stand-in for a FastAPI Request — decorator reads headers + client."""

    headers = {"user-agent": "pytest"}
    client = type("c", (), {"host": "127.0.0.1"})()


def _auth() -> AuthContext:
    """Real AuthContext so the decorator's isinstance check passes."""
    return AuthContext(user_id="user_admin_123")


@pytest.mark.asyncio
async def test_audit_uses_static_target_override():
    """When target_user_id_override is passed, the audit row uses it verbatim
    rather than pulling from kwargs."""
    create_mock = AsyncMock(return_value={})

    @audit_admin_action("catalog.test", target_user_id_override="__catalog__")
    async def handler(request, auth):
        return {"ok": True}

    with patch(
        "core.repositories.admin_actions_repo.create",
        new=create_mock,
    ):
        await handler(request=_Req(), auth=_auth())

    assert create_mock.await_count == 1
    # repo.create is keyword-only; all fields land in kwargs.
    assert create_mock.await_args.kwargs["target_user_id"] == "__catalog__"


@pytest.mark.asyncio
async def test_audit_falls_back_to_kwarg_without_override():
    """Sanity: existing behavior is preserved when no override is given."""
    create_mock = AsyncMock(return_value={})

    @audit_admin_action("user.test")
    async def handler(user_id, request, auth):
        return {"ok": True}

    with patch(
        "core.repositories.admin_actions_repo.create",
        new=create_mock,
    ):
        await handler(user_id="user_target_xyz", request=_Req(), auth=_auth())

    assert create_mock.await_count == 1
    assert create_mock.await_args.kwargs["target_user_id"] == "user_target_xyz"
