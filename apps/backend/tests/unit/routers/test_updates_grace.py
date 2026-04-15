"""Tests for admin-patch grace window on routers/updates.py."""

import os
from unittest.mock import AsyncMock, patch

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from main import app

    return TestClient(app)


def _patch_auth():
    from core.auth import AuthContext, get_current_user
    from main import app

    app.dependency_overrides[get_current_user] = lambda: AuthContext(user_id="u_admin")
    return lambda: app.dependency_overrides.pop(get_current_user, None)


def test_admin_single_config_patch_sets_grace(client):
    cleanup = _patch_auth()
    try:
        with (
            patch("routers.updates.patch_openclaw_config", AsyncMock()),
            patch("routers.updates.container_repo.set_reconciler_grace", AsyncMock()) as set_grace,
        ):
            resp = client.patch("/api/v1/container/config/owner_1", json={"patch": {"tools": {}}})
        assert resp.status_code == 200
        set_grace.assert_awaited_once_with("owner_1", seconds=5)
    finally:
        cleanup()
