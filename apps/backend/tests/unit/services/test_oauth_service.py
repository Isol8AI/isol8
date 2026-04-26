"""Unit tests for the ChatGPT device-code OAuth orchestration."""

from unittest.mock import patch

import boto3
import httpx
import pytest
from cryptography.fernet import Fernet
from moto import mock_aws

from core.services.oauth_service import (
    DevicePollPending,
    DevicePollResult,
    poll_device_code,
    request_device_code,
    revoke_user_oauth,
)


@pytest.fixture
def oauth_table(monkeypatch):
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName="test-oauth-tokens",
            KeySchema=[{"AttributeName": "user_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "user_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        monkeypatch.setenv("OAUTH_TOKENS_TABLE", "test-oauth-tokens")
        monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
        yield


@pytest.mark.asyncio
async def test_request_device_code_returns_user_facing_fields(oauth_table):
    """Backend POST to OpenAI device endpoint returns the user-code + URL."""

    fake_resp = {
        "device_code": "dev_abc",
        "user_code": "ABCD-1234",
        "verification_uri": "https://chatgpt.com/codex",
        "expires_in": 900,
        "interval": 5,
    }

    async def fake_post(self, url, **kwargs):
        return httpx.Response(200, json=fake_resp, request=httpx.Request("POST", url))

    with patch.object(httpx.AsyncClient, "post", new=fake_post):
        result = await request_device_code(user_id="u_1")

    assert result.user_code == "ABCD-1234"
    assert result.verification_uri == "https://chatgpt.com/codex"
    assert result.interval == 5
    # Server-side device_code is NOT returned to the caller — kept in DDB.
    assert not hasattr(result, "device_code")


@pytest.mark.asyncio
async def test_poll_pending_returns_pending(oauth_table):
    """OpenAI 'authorization_pending' translates to DevicePollPending."""

    # First seed a device-code session.
    seed_resp = {
        "device_code": "dev_pending",
        "user_code": "WAIT-0001",
        "verification_uri": "https://chatgpt.com/codex",
        "expires_in": 900,
        "interval": 5,
    }

    async def fake_seed(self, url, **kwargs):
        return httpx.Response(200, json=seed_resp, request=httpx.Request("POST", url))

    with patch.object(httpx.AsyncClient, "post", new=fake_seed):
        await request_device_code(user_id="u_1")

    # Then poll while still pending.
    async def fake_poll(self, url, **kwargs):
        return httpx.Response(
            400,
            json={"error": "authorization_pending"},
            request=httpx.Request("POST", url),
        )

    with patch.object(httpx.AsyncClient, "post", new=fake_poll):
        result = await poll_device_code(user_id="u_1")

    assert result is DevicePollPending


@pytest.mark.asyncio
async def test_poll_success_persists_encrypted_tokens(oauth_table):
    """Successful poll: tokens are Fernet-encrypted into the DDB row."""

    seed_resp = {
        "device_code": "dev_success",
        "user_code": "OKAY-9999",
        "verification_uri": "https://chatgpt.com/codex",
        "expires_in": 900,
        "interval": 5,
    }

    async def fake_seed(self, url, **kwargs):
        return httpx.Response(200, json=seed_resp, request=httpx.Request("POST", url))

    with patch.object(httpx.AsyncClient, "post", new=fake_seed):
        await request_device_code(user_id="u_1")

    success_resp = {
        "access_token": "eyJ.fake-jwt.access",
        "refresh_token": "rt_opaque_1",
        "id_token": "eyJ.id-token.x",
        "account_id": "chatgpt-account-1",
    }

    async def fake_success(self, url, **kwargs):
        return httpx.Response(200, json=success_resp, request=httpx.Request("POST", url))

    with patch.object(httpx.AsyncClient, "post", new=fake_success):
        result = await poll_device_code(user_id="u_1")

    assert isinstance(result, DevicePollResult)
    # Tokens are stored encrypted, so the raw DDB row should NOT contain them
    # in plaintext.
    client = boto3.client("dynamodb", region_name="us-east-1")
    raw_item = client.get_item(TableName="test-oauth-tokens", Key={"user_id": {"S": "u_1"}})["Item"]
    raw_payload_b = raw_item["encrypted_tokens"]["B"]
    assert b"eyJ.fake-jwt.access" not in raw_payload_b
    assert b"rt_opaque_1" not in raw_payload_b


@pytest.mark.asyncio
async def test_revoke_deletes_oauth_row(oauth_table):
    """revoke_user_oauth removes the persisted token row."""

    seed_resp = {
        "device_code": "dev_revoke",
        "user_code": "BYE-0001",
        "verification_uri": "https://chatgpt.com/codex",
        "expires_in": 900,
        "interval": 5,
    }
    success_resp = {
        "access_token": "eyJ.x.y",
        "refresh_token": "rt",
        "id_token": "eyJ.z",
        "account_id": "acc",
    }

    async def fake_seed(self, url, **kwargs):
        return httpx.Response(200, json=seed_resp, request=httpx.Request("POST", url))

    async def fake_success(self, url, **kwargs):
        return httpx.Response(200, json=success_resp, request=httpx.Request("POST", url))

    with patch.object(httpx.AsyncClient, "post", new=fake_seed):
        await request_device_code(user_id="u_1")
    with patch.object(httpx.AsyncClient, "post", new=fake_success):
        await poll_device_code(user_id="u_1")

    await revoke_user_oauth(user_id="u_1")

    client = boto3.client("dynamodb", region_name="us-east-1")
    resp = client.get_item(TableName="test-oauth-tokens", Key={"user_id": {"S": "u_1"}})
    assert "Item" not in resp
