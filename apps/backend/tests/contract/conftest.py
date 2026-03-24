"""
Contract test fixtures.

Uses httpx AsyncClient with ASGITransport and mocked auth dependencies.
No real database, gateway, or Clerk needed.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from core.auth import AuthContext


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
