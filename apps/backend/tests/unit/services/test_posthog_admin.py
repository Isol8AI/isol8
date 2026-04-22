"""Tests for the PostHog Persons API admin client.

Covers:
- Stubbed mode when POSTHOG_PROJECT_API_KEY unset (CEO local-dev requirement).
- Happy path: persons → events flattened, $session_id surfaced.
- 404 → missing=True (CEO E5).
- 5xx / timeout → graceful error response.
- Auth header sent (Bearer).
- session_replay_url helper.

Mocks httpx.AsyncClient directly via unittest.mock — respx 0.20.2 has
a compat issue with newer httpx where even identical URL strings don't
match, so we patch the client surface instead.
"""

import os
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")


def _make_response(status_code: int, json_body: dict | None = None, text_body: str = "") -> MagicMock:
    """Build a mock httpx.Response."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json = MagicMock(return_value=json_body or {})
    response.text = text_body
    return response


@asynccontextmanager
async def _fake_client(response_or_exc):
    """Async context manager that yields a fake AsyncClient.

    response_or_exc: either a Response (returned by .get) or an Exception
    (raised by .get).
    """
    client = MagicMock()
    if isinstance(response_or_exc, BaseException):
        client.get = AsyncMock(side_effect=response_or_exc)
    else:
        client.get = AsyncMock(return_value=response_or_exc)
    yield client


@pytest.mark.asyncio
async def test_stubs_when_api_key_unset(monkeypatch):
    monkeypatch.setattr("core.config.settings.POSTHOG_PROJECT_API_KEY", "")
    monkeypatch.setattr("core.config.settings.POSTHOG_PROJECT_ID", "12345")

    from core.services.posthog_admin import get_person_events

    result = await get_person_events(distinct_id="user_test", limit=10)
    assert result["stubbed"] is True
    assert result["events"] == []
    assert result["missing"] is False


@pytest.mark.asyncio
async def test_stubs_when_project_id_unset(monkeypatch):
    monkeypatch.setattr("core.config.settings.POSTHOG_PROJECT_API_KEY", "phc_xyz")
    monkeypatch.setattr("core.config.settings.POSTHOG_PROJECT_ID", "")

    from core.services.posthog_admin import get_person_events

    result = await get_person_events(distinct_id="user_test")
    assert result["stubbed"] is True


@pytest.mark.asyncio
async def test_happy_path_flattens_persons_to_events(monkeypatch):
    monkeypatch.setattr("core.config.settings.POSTHOG_HOST", "https://app.posthog.com")
    monkeypatch.setattr("core.config.settings.POSTHOG_PROJECT_ID", "12345")
    monkeypatch.setattr("core.config.settings.POSTHOG_PROJECT_API_KEY", "phc_xyz")

    body = {
        "results": [
            {
                "events": [
                    {
                        "timestamp": "2026-04-21T10:00:00Z",
                        "event": "$pageview",
                        "properties": {"$current_url": "/chat", "$session_id": "sess_a"},
                    },
                    {
                        "timestamp": "2026-04-21T10:01:00Z",
                        "event": "agent_chat_started",
                        "properties": {"agent_id": "agent_x", "$session_id": "sess_a"},
                    },
                ],
            },
        ],
    }
    response = _make_response(200, json_body=body)

    with patch(
        "core.services.posthog_admin.httpx.AsyncClient",
        new=lambda *a, **k: _fake_client(response),
    ):
        from core.services.posthog_admin import get_person_events

        result = await get_person_events(distinct_id="user_test", limit=20)

    assert result["stubbed"] is False
    assert result["missing"] is False
    assert result["error"] is None
    assert len(result["events"]) == 2
    e0 = result["events"][0]
    assert e0["event"] == "$pageview"
    assert e0["session_id"] == "sess_a"
    assert e0["properties"]["$current_url"] == "/chat"


@pytest.mark.asyncio
async def test_404_returns_missing(monkeypatch):
    monkeypatch.setattr("core.config.settings.POSTHOG_HOST", "https://app.posthog.com")
    monkeypatch.setattr("core.config.settings.POSTHOG_PROJECT_ID", "12345")
    monkeypatch.setattr("core.config.settings.POSTHOG_PROJECT_API_KEY", "phc_xyz")

    response = _make_response(404, json_body={})
    with patch(
        "core.services.posthog_admin.httpx.AsyncClient",
        new=lambda *a, **k: _fake_client(response),
    ):
        from core.services.posthog_admin import get_person_events

        result = await get_person_events(distinct_id="user_missing")

    assert result["missing"] is True
    assert result["events"] == []
    assert result["error"] is None


@pytest.mark.asyncio
async def test_5xx_returns_error(monkeypatch):
    monkeypatch.setattr("core.config.settings.POSTHOG_HOST", "https://app.posthog.com")
    monkeypatch.setattr("core.config.settings.POSTHOG_PROJECT_ID", "12345")
    monkeypatch.setattr("core.config.settings.POSTHOG_PROJECT_API_KEY", "phc_xyz")

    response = _make_response(503, text_body="upstream down")
    with patch(
        "core.services.posthog_admin.httpx.AsyncClient",
        new=lambda *a, **k: _fake_client(response),
    ):
        from core.services.posthog_admin import get_person_events

        result = await get_person_events(distinct_id="user_test")

    assert result["error"] == "http_503"
    assert result["events"] == []
    assert result["missing"] is False


@pytest.mark.asyncio
async def test_timeout_returns_error(monkeypatch):
    monkeypatch.setattr("core.config.settings.POSTHOG_HOST", "https://app.posthog.com")
    monkeypatch.setattr("core.config.settings.POSTHOG_PROJECT_ID", "12345")
    monkeypatch.setattr("core.config.settings.POSTHOG_PROJECT_API_KEY", "phc_xyz")

    with patch(
        "core.services.posthog_admin.httpx.AsyncClient",
        new=lambda *a, **k: _fake_client(httpx.TimeoutException("slow")),
    ):
        from core.services.posthog_admin import get_person_events

        result = await get_person_events(distinct_id="user_test")

    assert result["error"] == "timeout"


@pytest.mark.asyncio
async def test_authorization_header_includes_bearer_token(monkeypatch):
    monkeypatch.setattr("core.config.settings.POSTHOG_HOST", "https://app.posthog.com")
    monkeypatch.setattr("core.config.settings.POSTHOG_PROJECT_ID", "12345")
    monkeypatch.setattr("core.config.settings.POSTHOG_PROJECT_API_KEY", "phc_secret_value")

    captured_kwargs = {}
    response = _make_response(200, json_body={"results": []})

    @asynccontextmanager
    async def capturing_client(*args, **kwargs):
        client = MagicMock()

        async def get(url, headers=None, params=None, **kw):
            captured_kwargs["url"] = url
            captured_kwargs["headers"] = headers
            captured_kwargs["params"] = params
            return response

        client.get = get
        yield client

    with patch("core.services.posthog_admin.httpx.AsyncClient", new=capturing_client):
        from core.services.posthog_admin import get_person_events

        await get_person_events(distinct_id="user_test")

    assert captured_kwargs["headers"]["Authorization"] == "Bearer phc_secret_value"
    assert captured_kwargs["params"]["distinct_id"] == "user_test"


def test_session_replay_url(monkeypatch):
    monkeypatch.setattr("core.config.settings.POSTHOG_HOST", "https://app.posthog.com")
    from core.services.posthog_admin import session_replay_url

    assert session_replay_url("sess_abc") == "https://app.posthog.com/replay/sess_abc"
