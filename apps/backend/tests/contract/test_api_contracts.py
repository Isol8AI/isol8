"""
Schemathesis contract tests.

Auto-validates all API endpoints against the OpenAPI specification.
Uses ASGI transport so no running server is needed.

With mocked dependencies, endpoints that require external services
(gateway, DynamoDB, Clerk webhook verification) are excluded from automated
fuzz testing since they cannot be meaningfully tested without infrastructure.
"""

import schemathesis
from schemathesis.checks import not_a_server_error

from core.auth import AuthContext


def _make_app():
    """Create a FastAPI app with mocked dependencies for contract testing."""
    from main import app
    from core.auth import get_current_user

    mock_auth = AuthContext(user_id="contract_test_user")

    async def mock_get_current_user():
        return mock_auth

    app.dependency_overrides[get_current_user] = mock_get_current_user
    return app


app = _make_app()

# Exclude endpoints that require infrastructure not available in mock mode:
# - /ws/* endpoints need API Gateway + DynamoDB connection state
# - /webhooks/* need Clerk signature verification + real webhook payloads
# - Agent write operations need gateway for workspace management
schema = schemathesis.openapi.from_asgi("/api/v1/openapi.json", app=app)
schema = (
    schema.exclude(
        path_regex="^/api/v1/ws/",
    )
    .exclude(
        path_regex="^/api/v1/webhooks/",
    )
    .exclude(
        path_regex="^/api/v1/billing/",
    )
    .exclude(
        path_regex="^/api/v1/container/",
    )
    .exclude(
        path_regex="^/api/v1/debug/",
    )
    .exclude(
        path_regex="^/api/v1/channels/",
    )
    .exclude(
        path_regex="^/api/v1/proxy/",
    )
    .exclude(
        path_regex="^/api/v1/settings/",
    )
    .exclude(
        path_regex="^/api/v1/integrations/",
    )
    .exclude(
        path_regex="^/api/v1/users/",
    )
    .exclude(
        path_regex="^/health$",
    )
)


@schema.parametrize()
def test_no_server_errors(case):
    """No endpoint should return 5xx for schema-valid requests.

    This catches unhandled exceptions, missing error handling, and
    crashes from unexpected input shapes. Only checks for server errors;
    does not validate response schemas or status code documentation.

    Excluded endpoints (require infrastructure):
    - WebSocket routes (/ws/*) - need API Gateway + DynamoDB
    - Webhook routes (/webhooks/*) - need Clerk signature verification
    - Agent write operations - need gateway for workspace management
    - Health check (/health) - needs DynamoDB connectivity
    - Users (/users/*) - needs DynamoDB user repo
    """
    case.call_and_validate(checks=[not_a_server_error])
