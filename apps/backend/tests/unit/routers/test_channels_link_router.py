"""Tests for channels router — link endpoints + admin delete."""

import os
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

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


def test_link_complete_happy_path(client):
    cleanup = _patch_auth(_personal_auth("user_bob"))
    try:
        with patch(
            "routers.channels.channel_link_service.complete_link",
            AsyncMock(return_value={"status": "linked", "peer_id": "12345"}),
        ) as mock_link:
            resp = client.post(
                "/api/v1/channels/link/telegram/complete",
                json={"agent_id": "main", "code": "XYZ98765"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "linked"
        assert resp.json()["peer_id"] == "12345"
        mock_link.assert_awaited_once()
        kwargs = mock_link.call_args.kwargs
        assert kwargs["owner_id"] == "user_bob"
        assert kwargs["provider"] == "telegram"
        assert kwargs["agent_id"] == "main"
        assert kwargs["code"] == "XYZ98765"
        assert kwargs["member_id"] == "user_bob"
    finally:
        cleanup()


def test_link_complete_code_not_found_returns_404(client):
    cleanup = _patch_auth(_personal_auth())
    try:
        from core.services.channel_link_service import PairingCodeNotFoundError

        with patch(
            "routers.channels.channel_link_service.complete_link",
            AsyncMock(side_effect=PairingCodeNotFoundError("not found")),
        ):
            resp = client.post(
                "/api/v1/channels/link/telegram/complete",
                json={"agent_id": "main", "code": "BAD"},
            )
        assert resp.status_code == 404
    finally:
        cleanup()


def test_link_complete_peer_already_linked_returns_409(client):
    cleanup = _patch_auth(_personal_auth())
    try:
        from core.services.channel_link_service import PeerAlreadyLinkedError

        with patch(
            "routers.channels.channel_link_service.complete_link",
            AsyncMock(side_effect=PeerAlreadyLinkedError("taken")),
        ):
            resp = client.post(
                "/api/v1/channels/link/telegram/complete",
                json={"agent_id": "main", "code": "XYZ98765"},
            )
        assert resp.status_code == 409
    finally:
        cleanup()


def test_link_complete_unsupported_provider_returns_400(client):
    cleanup = _patch_auth(_personal_auth())
    try:
        resp = client.post(
            "/api/v1/channels/link/whatsapp/complete",
            json={"agent_id": "main", "code": "XYZ"},
        )
        assert resp.status_code == 400
    finally:
        cleanup()


def test_link_complete_uses_member_id_not_owner_for_org_callers(client):
    # NOTE: AuthContext has NO email field
    auth = AuthContext(
        user_id="user_bob",
        org_id="org_1",
        org_role="org:member",
    )
    cleanup = _patch_auth(auth)
    try:
        with patch(
            "routers.channels.channel_link_service.complete_link",
            AsyncMock(return_value={"status": "linked", "peer_id": "12345"}),
        ) as mock_link:
            resp = client.post(
                "/api/v1/channels/link/telegram/complete",
                json={"agent_id": "main", "code": "XYZ98765"},
            )
        assert resp.status_code == 200
        kwargs = mock_link.call_args.kwargs
        assert kwargs["owner_id"] == "org_1"
        assert kwargs["member_id"] == "user_bob"
    finally:
        cleanup()
