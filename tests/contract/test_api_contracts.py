"""
Schemathesis contract tests.

Auto-validates all API endpoints against the OpenAPI specification.
Uses ASGI transport so no running server is needed.

With mocked database dependencies, endpoints that require external services
(gateway, DynamoDB, Clerk webhook verification) are excluded from automated
fuzz testing since they cannot be meaningfully tested without infrastructure.
"""

import schemathesis
from schemathesis.checks import not_a_server_error
from unittest.mock import AsyncMock, MagicMock, patch

from core.auth import AuthContext


def _make_app():
    """Create a FastAPI app with mocked dependencies for contract testing."""
    from main import app
    from core.auth import get_current_user
    from core.database import get_db, get_session_factory

    mock_auth = AuthContext(user_id="contract_test_user")

    async def mock_get_current_user():
        return mock_auth

    async def mock_get_db():
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_result.scalars.return_value.all.return_value = []
        mock_result.scalar_one_or_none.return_value = None
        mock_result.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        yield mock_session

    def mock_get_session_factory():
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_result.scalars.return_value.all.return_value = []
        mock_result.scalar_one_or_none.return_value = None
        mock_result.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()

        class _Ctx:
            def __call__(self):
                return self

            async def __aenter__(self):
                return mock_session

            async def __aexit__(self, *_):
                pass

        return _Ctx()

    app.dependency_overrides[get_current_user] = mock_get_current_user
    app.dependency_overrides[get_db] = mock_get_db
    app.dependency_overrides[get_session_factory] = mock_get_session_factory
    return app


# Patch TownSimulation before loading schema
# so schemathesis can create its internal ASGI client without lifespan errors.
_town_sim_patch = patch("main.TownSimulation")

_mock_town = _town_sim_patch.start()
_mock_town.return_value.start = AsyncMock()
_mock_town.return_value.stop = AsyncMock()

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
    """
    case.call_and_validate(checks=[not_a_server_error])
