"""
Contract test fixtures.

Uses httpx AsyncClient with ASGITransport and mocked auth dependencies.
No real database, gateway, or Clerk needed.
"""

import boto3
import httpx
import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from moto import mock_aws

from core.auth import AuthContext


@pytest.fixture(autouse=True)
def _mock_oauth_external_deps(monkeypatch):
    """Auto-applied to every contract test.

    The /oauth/chatgpt/{start,poll,disconnect} endpoints have two external
    dependencies that would 500 in the contract suite without mocking:

    1. A DynamoDB table named by the OAUTH_TOKENS_TABLE env var, plus an
       ENCRYPTION_KEY for Fernet — both raise RuntimeError("... is empty")
       if missing.
    2. httpx POSTs to auth.openai.com/{codex/device,oauth/token}, which
       fail with no network / no real OAuth flow.

    The contract suite only asserts non-5xx, so we mock both with moto +
    a deterministic httpx.AsyncClient.post that returns canned device-code
    + authorization_pending shapes. This keeps the mocks scoped to contract
    tests (autouse here, not in the global conftest).
    """
    # 1. Provision the OAuth tokens table in moto.
    mock = mock_aws()
    mock.start()
    try:
        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName="contract-test-oauth-tokens",
            KeySchema=[{"AttributeName": "user_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "user_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        monkeypatch.setenv("OAUTH_TOKENS_TABLE", "contract-test-oauth-tokens")
        monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())

        # Pre-seed a pending device-code session for the contract test user
        # so /poll has a row to look up. /start would normally create this
        # row, but schemathesis hits each endpoint independently.
        client.put_item(
            TableName="contract-test-oauth-tokens",
            Item={
                "user_id": {"S": "contract_test_user"},
                "state": {"S": "pending"},
                "device_code": {"S": "ct_dev_code"},
                "user_code": {"S": "CONT-RACT"},
                "interval": {"N": "5"},
            },
        )

        # 2. Replace httpx.AsyncClient *only inside core.services.oauth_service*
        # so the OpenAI device-code/token URLs return canned responses. We
        # avoid monkey-patching httpx.AsyncClient.post globally because the
        # contract suite's test client (httpx.AsyncClient + ASGITransport) is
        # also an httpx.AsyncClient — a global patch would intercept the
        # test client's own requests and break unrelated contract tests.
        class _FakeOAuthClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            async def post(self, url, **kwargs):
                url_str = str(url)
                if "/codex/device" in url_str:
                    return httpx.Response(
                        200,
                        json={
                            "device_code": "ct_dev_code",
                            "user_code": "CONT-RACT",
                            "verification_uri": "https://chatgpt.com/codex",
                            "expires_in": 900,
                            "interval": 5,
                        },
                        request=httpx.Request("POST", url),
                    )
                if "/oauth/token" in url_str:
                    # Pretend the user is still pending so /poll returns 200
                    # with status=pending instead of erroring.
                    return httpx.Response(
                        400,
                        json={"error": "authorization_pending"},
                        request=httpx.Request("POST", url),
                    )
                return httpx.Response(200, json={}, request=httpx.Request("POST", url))

        import core.services.oauth_service as oauth_module

        monkeypatch.setattr(oauth_module.httpx, "AsyncClient", _FakeOAuthClient)
        yield
    finally:
        mock.stop()


@pytest.fixture
def mock_auth():
    """Mock auth context for contract tests."""
    return AuthContext(user_id="contract_test_user")


@pytest.fixture
async def contract_client(mock_auth):
    """
    Async test client for contract tests.

    Overrides auth dependency so tests don't need real infrastructure.
    """
    from main import app
    from core.auth import get_current_user

    async def mock_get_current_user():
        return mock_auth

    app.dependency_overrides[get_current_user] = mock_get_current_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture
async def openapi_spec(contract_client):
    """Fetch and return the OpenAPI spec as a dict."""
    response = await contract_client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    return response.json()
