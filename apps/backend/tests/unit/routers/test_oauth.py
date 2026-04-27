"""Integration tests for /api/v1/oauth/chatgpt/* endpoints."""

from unittest.mock import AsyncMock, patch

import pytest

from core.services.oauth_service import (
    DeviceCodeResponse,
    DevicePollPending,
    DevicePollResult,
    OAuthAlreadyActiveError,
)


@pytest.mark.asyncio
async def test_start_returns_user_code_and_verification_uri(async_client):
    fake_resp = DeviceCodeResponse(
        user_code="TEST-1234",
        verification_uri="https://chatgpt.com/codex",
        expires_in=900,
        interval=5,
    )
    with patch(
        "routers.oauth.request_device_code",
        new=AsyncMock(return_value=fake_resp),
    ):
        resp = await async_client.post("/api/v1/oauth/chatgpt/start")
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_code"] == "TEST-1234"
    assert body["verification_uri"] == "https://chatgpt.com/codex"
    assert body["interval"] == 5
    assert body["expires_in"] == 900


@pytest.mark.asyncio
async def test_start_returns_409_when_already_active(async_client):
    """When user already has an active OAuth session, /start returns 409."""
    with patch(
        "routers.oauth.request_device_code",
        new=AsyncMock(side_effect=OAuthAlreadyActiveError("already active")),
    ):
        resp = await async_client.post("/api/v1/oauth/chatgpt/start")
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_poll_returns_pending_status(async_client):
    with patch(
        "routers.oauth.poll_device_code",
        new=AsyncMock(return_value=DevicePollPending),
    ):
        resp = await async_client.post("/api/v1/oauth/chatgpt/poll")
    assert resp.status_code == 200
    assert resp.json() == {"status": "pending"}


@pytest.mark.asyncio
async def test_poll_returns_completed_status(async_client):
    with patch(
        "routers.oauth.poll_device_code",
        new=AsyncMock(return_value=DevicePollResult(account_id="acc_1")),
    ):
        resp = await async_client.post("/api/v1/oauth/chatgpt/poll")
    assert resp.status_code == 200
    assert resp.json() == {"status": "completed", "account_id": "acc_1"}


@pytest.mark.asyncio
async def test_disconnect_revokes(async_client):
    with patch("routers.oauth.revoke_user_oauth", new=AsyncMock()) as mock_revoke:
        resp = await async_client.post("/api/v1/oauth/chatgpt/disconnect")
    assert resp.status_code == 200
    mock_revoke.assert_awaited_once()
