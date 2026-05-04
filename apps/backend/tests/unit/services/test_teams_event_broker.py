"""Unit tests for TeamsEventBroker — the per-user fanout layer that owns
PaperclipEventClient instances and routes events to subscribed browser
connection IDs via the API Gateway Management API.
"""

from __future__ import annotations

import asyncio
import os
from typing import Awaitable, Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")


class FakeClient:
    """Stand-in for PaperclipEventClient — captures lifecycle calls and
    exposes a ``trigger(event)`` helper to simulate upstream events."""

    def __init__(self, on_event: Callable[[dict], Awaitable[None]]):
        self._on_event = on_event
        self.start_called = 0
        self.close_called = 0

    async def start(self) -> None:
        self.start_called += 1

    async def close(self) -> None:
        self.close_called += 1

    async def trigger(self, event: dict) -> None:
        await self._on_event(event)


@pytest.fixture
def fake_components(monkeypatch):
    """Patch the broker's dependencies so we never hit real DDB / WS / API GW."""
    fake_clients: list[FakeClient] = []
    fake_mgmt = MagicMock()
    fake_mgmt.send_message = MagicMock(return_value=True)
    fake_conn_svc = MagicMock()
    fake_conn_svc.query_by_user_id = AsyncMock(return_value=[])
    fake_conn_svc.delete_connection = MagicMock()

    def _client_factory(*, user_id, company_id, cookie, on_event):
        c = FakeClient(on_event)
        fake_clients.append(c)
        return c

    async def _resolve_company_id(_user_id: str) -> str:
        return f"co_{_user_id}"

    async def _resolve_cookie(_user_id: str) -> str:
        return "fake-cookie"

    return {
        "clients": fake_clients,
        "mgmt": fake_mgmt,
        "conn_svc": fake_conn_svc,
        "client_factory": _client_factory,
        "resolve_company_id": _resolve_company_id,
        "resolve_cookie": _resolve_cookie,
    }


def _build_broker(fc, *, grace_seconds: float = 30.0):
    from core.services.teams_event_broker import TeamsEventBroker

    return TeamsEventBroker(
        client_factory=fc["client_factory"],
        management_api=fc["mgmt"],
        connection_service=fc["conn_svc"],
        resolve_company_id=fc["resolve_company_id"],
        resolve_session_cookie=fc["resolve_cookie"],
        grace_seconds=grace_seconds,
    )


@pytest.mark.asyncio
async def test_subscribe_starts_backing_client_once_per_user(fake_components):
    broker = _build_broker(fake_components)
    await broker.subscribe("user_a", "conn_1")
    await broker.subscribe("user_a", "conn_2")  # second tab

    assert len(fake_components["clients"]) == 1  # ONE client for the user
    assert fake_components["clients"][0].start_called == 1
    await broker.shutdown()


@pytest.mark.asyncio
async def test_subscribe_distinct_users_creates_distinct_clients(fake_components):
    broker = _build_broker(fake_components)
    await broker.subscribe("user_a", "conn_a")
    await broker.subscribe("user_b", "conn_b")

    assert len(fake_components["clients"]) == 2
    await broker.shutdown()


@pytest.mark.asyncio
async def test_event_fanout_to_all_user_subscribers(fake_components):
    broker = _build_broker(fake_components)
    await broker.subscribe("user_a", "conn_1")
    await broker.subscribe("user_a", "conn_2")
    fake_components["conn_svc"].query_by_user_id.return_value = ["conn_1", "conn_2"]

    await fake_components["clients"][0].trigger(
        {
            "id": 1,
            "companyId": "co_user_a",
            "type": "activity.logged",
            "createdAt": "2026-05-04T01:00:00Z",
            "payload": {"actor": "x"},
        }
    )

    sent_to = [c.kwargs.get("connection_id") or c.args[0] for c in fake_components["mgmt"].send_message.call_args_list]
    assert sorted(sent_to) == ["conn_1", "conn_2"]

    # Verify wrapper shape: type=event, event prefix teams., payload pass-through.
    payload = fake_components["mgmt"].send_message.call_args_list[0].args[1]
    assert payload["type"] == "event"
    assert payload["event"] == "teams.activity.logged"
    assert payload["payload"] == {"actor": "x"}
    await broker.shutdown()


@pytest.mark.asyncio
async def test_synthetic_resumed_event_fans_out_as_teams_stream_resumed(fake_components):
    broker = _build_broker(fake_components)
    await broker.subscribe("user_a", "conn_1")
    fake_components["conn_svc"].query_by_user_id.return_value = ["conn_1"]

    # Client emits the synthetic resumed (no companyId / payload).
    await fake_components["clients"][0].trigger({"type": "stream.resumed"})

    payload = fake_components["mgmt"].send_message.call_args_list[0].args[1]
    assert payload["type"] == "event"
    assert payload["event"] == "teams.stream.resumed"
    assert payload["payload"] == {}
    await broker.shutdown()


@pytest.mark.asyncio
async def test_unsubscribe_starts_grace_period_then_closes(fake_components):
    broker = _build_broker(fake_components, grace_seconds=0.05)
    await broker.subscribe("user_a", "conn_1")
    await broker.unsubscribe("user_a", "conn_1")

    # Within the grace period, client is still alive.
    assert fake_components["clients"][0].close_called == 0
    await asyncio.sleep(0.15)
    assert fake_components["clients"][0].close_called == 1
    await broker.shutdown()


@pytest.mark.asyncio
async def test_resubscribe_during_grace_cancels_teardown(fake_components):
    broker = _build_broker(fake_components, grace_seconds=0.1)
    await broker.subscribe("user_a", "conn_1")
    await broker.unsubscribe("user_a", "conn_1")
    await asyncio.sleep(0.02)
    await broker.subscribe("user_a", "conn_2")  # rejoin within grace
    await asyncio.sleep(0.2)  # well past the original grace window

    assert fake_components["clients"][0].close_called == 0
    assert len(fake_components["clients"]) == 1  # no new client opened
    await broker.shutdown()


@pytest.mark.asyncio
async def test_stale_connection_cleaned_up_on_send_false(fake_components):
    broker = _build_broker(fake_components)
    await broker.subscribe("user_a", "conn_1")
    fake_components["conn_svc"].query_by_user_id.return_value = ["conn_1"]
    fake_components["mgmt"].send_message.return_value = False  # GoneException

    await fake_components["clients"][0].trigger(
        {
            "id": 1,
            "companyId": "co_user_a",
            "type": "agent.status",
            "createdAt": "2026-05-04T01:00:00Z",
            "payload": {},
        }
    )

    fake_components["conn_svc"].delete_connection.assert_called_once_with("conn_1")
    await broker.shutdown()


@pytest.mark.asyncio
async def test_concurrent_subscribes_do_not_double_open_client(fake_components):
    broker = _build_broker(fake_components)
    await asyncio.gather(
        broker.subscribe("user_a", "c1"),
        broker.subscribe("user_a", "c2"),
        broker.subscribe("user_a", "c3"),
    )
    assert len(fake_components["clients"]) == 1
    await broker.shutdown()


@pytest.mark.asyncio
async def test_subscribe_emits_subscribe_ok_metric(fake_components):
    """Happy path: first subscribe emits teams.broker.subscribe outcome=ok."""
    with patch("core.services.teams_event_broker.put_metric") as put_metric_mock:
        broker = _build_broker(fake_components)
        await broker.subscribe("user_a", "conn_1")
        await broker.shutdown()

    matching = [
        c
        for c in put_metric_mock.call_args_list
        if c.args and c.args[0] == "teams.broker.subscribe" and c.kwargs.get("dimensions", {}).get("outcome") == "ok"
    ]
    assert matching, (
        f"expected teams.broker.subscribe ok; got: {[(c.args, c.kwargs) for c in put_metric_mock.call_args_list]}"
    )


@pytest.mark.asyncio
async def test_event_handling_emits_received_and_fanout_ok_metrics(fake_components):
    """Happy path: an event triggers teams.broker.event.received +
    teams.broker.fanout outcome=ok per connection sent to."""
    broker = _build_broker(fake_components)
    await broker.subscribe("user_a", "conn_1")
    fake_components["conn_svc"].query_by_user_id.return_value = ["conn_1"]

    with patch("core.services.teams_event_broker.put_metric") as put_metric_mock:
        await fake_components["clients"][0].trigger(
            {
                "id": 1,
                "companyId": "co_user_a",
                "type": "activity.logged",
                "createdAt": "2026-05-04T01:00:00Z",
                "payload": {"actor": "x"},
            }
        )

    received_calls = [
        c for c in put_metric_mock.call_args_list if c.args and c.args[0] == "teams.broker.event.received"
    ]
    fanout_ok_calls = [
        c
        for c in put_metric_mock.call_args_list
        if c.args and c.args[0] == "teams.broker.fanout" and c.kwargs.get("dimensions", {}).get("outcome") == "ok"
    ]
    assert received_calls, "expected teams.broker.event.received"
    assert fanout_ok_calls, "expected teams.broker.fanout outcome=ok"
    # event_type dimension should be set
    assert received_calls[0].kwargs.get("dimensions", {}).get("event_type") == "activity.logged"
    await broker.shutdown()


@pytest.mark.asyncio
async def test_grace_teardown_prunes_user_lock(fake_components):
    """After grace teardown completes, _locks[user_id] is removed so
    long-running processes don't accumulate per-former-user locks."""
    broker = _build_broker(fake_components, grace_seconds=0.05)
    await broker.subscribe("user_a", "conn_1")
    assert "user_a" in broker._locks
    await broker.unsubscribe("user_a", "conn_1")
    await asyncio.sleep(0.2)  # let grace teardown finish
    assert "user_a" not in broker._locks
    await broker.shutdown()
