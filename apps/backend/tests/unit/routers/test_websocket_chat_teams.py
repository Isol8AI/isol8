"""Unit tests for the new teams.subscribe / teams.unsubscribe routes
on the /ws/message dispatcher."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import BackgroundTasks
from fastapi.responses import Response

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")


def _conn_record(user_id: str = "u1", org_id: str | None = None) -> dict:
    return {"user_id": user_id, "org_id": org_id, "connection_type": "chat"}


@pytest.mark.asyncio
async def test_teams_subscribe_calls_broker_subscribe():
    from routers.websocket_chat import ws_message

    fake_conn_svc = MagicMock()
    fake_conn_svc.get_connection = MagicMock(return_value=_conn_record())
    fake_broker = MagicMock()
    fake_broker.subscribe = AsyncMock()
    fake_broker.unsubscribe = AsyncMock()

    with (
        patch("routers.websocket_chat.get_connection_service", AsyncMock(return_value=fake_conn_svc)),
        patch("routers.websocket_chat.get_management_api_client", AsyncMock(return_value=MagicMock())),
        patch("routers.websocket_chat.get_gateway_pool", MagicMock(return_value=MagicMock())),
        patch("core.services.teams_event_broker_singleton.get_broker", return_value=fake_broker),
    ):
        resp = await ws_message(
            body={"type": "teams.subscribe"},
            background_tasks=BackgroundTasks(),
            x_connection_id="conn_abc",
        )

    assert isinstance(resp, Response)
    assert resp.status_code == 200
    fake_broker.subscribe.assert_awaited_once_with("u1", "conn_abc")
    fake_broker.unsubscribe.assert_not_awaited()


@pytest.mark.asyncio
async def test_teams_unsubscribe_calls_broker_unsubscribe():
    from routers.websocket_chat import ws_message

    fake_conn_svc = MagicMock()
    fake_conn_svc.get_connection = MagicMock(return_value=_conn_record())
    fake_broker = MagicMock()
    fake_broker.subscribe = AsyncMock()
    fake_broker.unsubscribe = AsyncMock()

    with (
        patch("routers.websocket_chat.get_connection_service", AsyncMock(return_value=fake_conn_svc)),
        patch("routers.websocket_chat.get_management_api_client", AsyncMock(return_value=MagicMock())),
        patch("routers.websocket_chat.get_gateway_pool", MagicMock(return_value=MagicMock())),
        patch("core.services.teams_event_broker_singleton.get_broker", return_value=fake_broker),
    ):
        resp = await ws_message(
            body={"type": "teams.unsubscribe"},
            background_tasks=BackgroundTasks(),
            x_connection_id="conn_abc",
        )

    assert resp.status_code == 200
    fake_broker.unsubscribe.assert_awaited_once_with("u1", "conn_abc")
    fake_broker.subscribe.assert_not_awaited()


@pytest.mark.asyncio
async def test_teams_subscribe_no_op_when_broker_unavailable():
    """If the singleton is None (dev without Paperclip env), subscribe
    silently 200s — /teams just won't get live updates."""
    from routers.websocket_chat import ws_message

    fake_conn_svc = MagicMock()
    fake_conn_svc.get_connection = MagicMock(return_value=_conn_record())

    with (
        patch("routers.websocket_chat.get_connection_service", AsyncMock(return_value=fake_conn_svc)),
        patch("routers.websocket_chat.get_management_api_client", AsyncMock(return_value=MagicMock())),
        patch("routers.websocket_chat.get_gateway_pool", MagicMock(return_value=MagicMock())),
        patch("core.services.teams_event_broker_singleton.get_broker", return_value=None),
    ):
        resp = await ws_message(
            body={"type": "teams.subscribe"},
            background_tasks=BackgroundTasks(),
            x_connection_id="conn_abc",
        )

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_existing_chat_message_types_still_routed():
    """Regression: adding teams.* must not break ping/agent_chat dispatch."""
    from routers.websocket_chat import ws_message

    fake_conn_svc = MagicMock()
    fake_conn_svc.get_connection = MagicMock(return_value=_conn_record())
    fake_mgmt = MagicMock()
    fake_mgmt.send_message = MagicMock()

    with (
        patch("routers.websocket_chat.get_connection_service", AsyncMock(return_value=fake_conn_svc)),
        patch("routers.websocket_chat.get_management_api_client", AsyncMock(return_value=fake_mgmt)),
        patch("routers.websocket_chat.get_gateway_pool", MagicMock(return_value=MagicMock())),
    ):
        resp = await ws_message(
            body={"type": "ping"},
            background_tasks=BackgroundTasks(),
            x_connection_id="conn_abc",
        )

    assert resp.status_code == 200
    fake_mgmt.send_message.assert_called_once()
    sent_payload = fake_mgmt.send_message.call_args.args[1]
    assert sent_payload == {"type": "pong"}
