"""Tests for channels router — link endpoints + admin delete."""

import os
import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")

from core.auth import AuthContext  # noqa: E402


@pytest.fixture
def client():
    from main import app

    return TestClient(app)


def _patch_auth(auth: AuthContext):
    from core.auth import get_current_user
    from main import app

    app.dependency_overrides[get_current_user] = lambda: auth
    return lambda: app.dependency_overrides.pop(get_current_user, None)


def _personal_auth(user_id: str = "user_personal") -> AuthContext:
    # Construct AuthContext matching the real signature (NO email param)
    return AuthContext(user_id=user_id, org_id=None, org_role=None)


def test_delete_bot_unsupported_provider_returns_400(client):
    cleanup = _patch_auth(_personal_auth())
    try:
        resp = client.delete("/api/v1/channels/link/whatsapp/main")
        assert resp.status_code == 400
    finally:
        cleanup()
