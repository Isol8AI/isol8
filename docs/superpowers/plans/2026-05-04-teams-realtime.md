# Teams Realtime Updates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire `/teams/*` panels to live updates by proxying Paperclip's per-company WebSocket through our existing API Gateway WS infra into a per-user backing connection on the FastAPI backend, fanning events out to subscribed browser tabs that drive SWR cache invalidation.

**Architecture:** Browser opens existing API Gateway WS. New `teams.subscribe` message creates a per-user backing WS to Paperclip's `/api/companies/{companyId}/events/ws` (Better-Auth cookie). Backend `TeamsEventBroker` fans events to all browser conn-IDs for that user via Management API. Frontend `TeamsEventsProvider` invalidates SWR keys per event type. No backfill on reconnect — invalidate everything instead.

**Tech Stack:** Python 3.12 / FastAPI / `websockets` / aioboto3 / pytest + AsyncMock + moto. TypeScript / React 19 / Next.js 16 / SWR / Vitest + RTL. AWS CDK (TypeScript) for the GSI schema change.

**Spec:** [`docs/superpowers/specs/2026-05-04-teams-realtime-design.md`](../specs/2026-05-04-teams-realtime-design.md)

---

## File structure

| File | Action | Responsibility |
|---|---|---|
| `apps/infra/lib/stacks/api-stack.ts` | Modify | Add `by-user-id` GSI (KEYS_ONLY) to `ws-connections` table |
| `apps/infra/lib/stacks/service-stack.ts` | Modify | Extend `DynamoDbConnections` IAM policy to include the GSI ARN |
| `apps/backend/core/services/connection_service.py` | Modify | Add `query_by_user_id(user_id) -> list[str]` using the new GSI |
| `apps/backend/core/services/paperclip_event_client.py` | Create | Per-user persistent WS to Paperclip events endpoint with reconnect + synthetic resume event |
| `apps/backend/core/services/teams_event_broker.py` | Create | Process-wide singleton: subscribe/unsubscribe, fanout, grace teardown |
| `apps/backend/routers/websocket_chat.py` | Modify | Add `teams.subscribe` and `teams.unsubscribe` message types to dispatcher |
| `apps/backend/main.py` | Modify | Lifespan: start/stop `teams_event_broker` |
| `apps/backend/tests/unit/services/test_paperclip_event_client.py` | Create | Unit tests with `websockets.serve` fake server |
| `apps/backend/tests/unit/services/test_teams_event_broker.py` | Create | Unit tests with mock client + mock management_api |
| `apps/backend/tests/unit/services/test_connection_service_query.py` | Create | Unit test for `query_by_user_id` (moto) |
| `apps/backend/tests/unit/routers/test_websocket_chat_teams.py` | Create | Unit test for the new `teams.subscribe` / `teams.unsubscribe` routes |
| `apps/frontend/src/app/teams/layout.tsx` | Modify | Wrap children in `<GatewayProvider>` |
| `apps/frontend/src/components/teams/TeamsEventsProvider.tsx` | Create | Mount inside `TeamsLayout`, drive SWR invalidations from gateway events |
| `apps/frontend/src/components/teams/TeamsLayout.tsx` | Modify | Mount `<TeamsEventsProvider>` |
| `apps/frontend/src/__tests__/teams/TeamsEventsProvider.test.tsx` | Create | Unit tests with mock `useGateway` |

---

## Task 1: CDK — Add GSI to `ws-connections` and grant Query on the index

**Files:**
- Modify: `apps/infra/lib/stacks/api-stack.ts:252-258`
- Modify: `apps/infra/lib/stacks/service-stack.ts:520-535`

- [ ] **Step 1: Edit `api-stack.ts` to add the GSI**

In `apps/infra/lib/stacks/api-stack.ts`, change the `ConnectionsTable` block (currently lines 252-258) to:

```ts
const connectionsTable = new dynamodb.Table(this, "ConnectionsTable", {
  tableName: `isol8-${env}-ws-connections`,
  partitionKey: { name: "connectionId", type: dynamodb.AttributeType.STRING },
  billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
  removalPolicy: cdk.RemovalPolicy.DESTROY,
  timeToLiveAttribute: "ttl",
});

// GSI to fan out realtime events from the Teams BFF: given a user_id,
// return every active browser WS connection for that user. KEYS_ONLY
// projection — broker only needs connectionId, full row lives at the
// base table. Spec: docs/superpowers/specs/2026-05-04-teams-realtime-design.md
connectionsTable.addGlobalSecondaryIndex({
  indexName: "by-user-id",
  partitionKey: { name: "userId", type: dynamodb.AttributeType.STRING },
  projectionType: dynamodb.ProjectionType.KEYS_ONLY,
});
```

- [ ] **Step 2: Edit `service-stack.ts` to grant Query on the GSI**

In `apps/infra/lib/stacks/service-stack.ts`, change the `DynamoDbConnections` policy statement (currently lines 520-535) to add the GSI ARN:

```ts
this.taskRole.addToPolicy(
  new iam.PolicyStatement({
    sid: "DynamoDbConnections",
    actions: [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:DeleteItem",
      "dynamodb:Query",
      "dynamodb:Scan",
    ],
    resources: [
      `arn:aws:dynamodb:${this.region}:${this.account}:table/${props.connectionsTableName}`,
      // GSI ARN — required to Query the by-user-id index added in
      // api-stack.ts. Without this, broker fanout queries 400 with
      // AccessDeniedException at runtime.
      `arn:aws:dynamodb:${this.region}:${this.account}:table/${props.connectionsTableName}/index/*`,
    ],
  }),
);
```

- [ ] **Step 3: Run `cdk synth` to verify the change**

Run: `cd apps/infra && pnpm cdk synth dev/isol8-dev/api 2>&1 | grep -A 3 "by-user-id"`
Expected: emits a `GlobalSecondaryIndexes` block with `IndexName: by-user-id`, `Projection: { ProjectionType: KEYS_ONLY }`.

- [ ] **Step 4: Commit**

```bash
git add apps/infra/lib/stacks/api-stack.ts apps/infra/lib/stacks/service-stack.ts
git commit -m "feat(infra): add by-user-id GSI to ws-connections + grant Query"
```

---

## Task 2: Backend — `ConnectionService.query_by_user_id`

**Files:**
- Modify: `apps/backend/core/services/connection_service.py`
- Test: `apps/backend/tests/unit/services/test_connection_service_query.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/unit/services/test_connection_service_query.py`:

```python
"""Unit tests for ConnectionService.query_by_user_id (the new GSI lookup)."""

from __future__ import annotations

import os
import boto3
import pytest
from moto import mock_aws

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")


@pytest.fixture
def ddb_table_with_gsi():
    """Stand up an in-memory DDB ws-connections table with the by-user-id GSI."""
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName="ws-conn-test",
            KeySchema=[{"AttributeName": "connectionId", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "connectionId", "AttributeType": "S"},
                {"AttributeName": "userId", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "by-user-id",
                    "KeySchema": [{"AttributeName": "userId", "KeyType": "HASH"}],
                    "Projection": {"ProjectionType": "KEYS_ONLY"},
                }
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield "ws-conn-test"


@pytest.mark.asyncio
async def test_query_by_user_id_returns_only_matching_user_conn_ids(ddb_table_with_gsi):
    from core.services.connection_service import ConnectionService

    svc = ConnectionService(table_name=ddb_table_with_gsi, region_name="us-east-1")
    svc.store_connection("conn_a1", "user_a", None)
    svc.store_connection("conn_a2", "user_a", None)
    svc.store_connection("conn_b1", "user_b", None)

    result = await svc.query_by_user_id("user_a")
    assert sorted(result) == ["conn_a1", "conn_a2"]

    result_b = await svc.query_by_user_id("user_b")
    assert result_b == ["conn_b1"]

    result_missing = await svc.query_by_user_id("user_nope")
    assert result_missing == []


@pytest.mark.asyncio
async def test_query_by_user_id_paginates(ddb_table_with_gsi):
    """Multiple page Query results aggregate into a single list."""
    from core.services.connection_service import ConnectionService

    svc = ConnectionService(table_name=ddb_table_with_gsi, region_name="us-east-1")
    for i in range(25):
        svc.store_connection(f"conn_{i:02d}", "user_p", None)

    result = await svc.query_by_user_id("user_p")
    assert len(result) == 25
    assert sorted(result) == sorted([f"conn_{i:02d}" for i in range(25)])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && uv run pytest tests/unit/services/test_connection_service_query.py -v --no-cov`
Expected: FAIL with `AttributeError: 'ConnectionService' object has no attribute 'query_by_user_id'`.

- [ ] **Step 3: Implement `query_by_user_id`**

Add this method to `apps/backend/core/services/connection_service.py` immediately after `count_for_user` (around line 188, before `delete_all_for_user`):

```python
    async def query_by_user_id(self, user_id: str) -> list[str]:
        """Return every active connection ID owned by ``user_id``.

        Uses the ``by-user-id`` GSI added in
        ``apps/infra/lib/stacks/api-stack.ts``. KEYS_ONLY projection means
        only ``connectionId`` is returned per row — sufficient for the
        TeamsEventBroker fanout. Paginates ``LastEvaluatedKey`` because a
        single Query page caps at ~1MB; in practice one page suffices
        (a typical user has 1-3 live tabs) but pagination keeps the
        contract correct under load.

        Returns an empty list if the user has no live connections.
        """

        def _query() -> list[str]:
            paginator = self._client.get_paginator("query")
            pages = paginator.paginate(
                TableName=self.table_name,
                IndexName="by-user-id",
                KeyConditionExpression="userId = :u",
                ExpressionAttributeValues={":u": {"S": user_id}},
                ProjectionExpression="connectionId",
            )
            ids: list[str] = []
            for page in pages:
                for item in page.get("Items", []):
                    ids.append(item["connectionId"]["S"])
            return ids

        try:
            return await asyncio.to_thread(_query)
        except ClientError as e:
            logger.error(
                "Failed to query connections for user %s: %s",
                user_id,
                e.response["Error"]["Message"],
            )
            raise ConnectionServiceError(
                f"Failed to query connections for user {user_id}: {e.response['Error']['Message']}"
            ) from e
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/backend && uv run pytest tests/unit/services/test_connection_service_query.py -v --no-cov`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/services/connection_service.py apps/backend/tests/unit/services/test_connection_service_query.py
git commit -m "feat(backend): ConnectionService.query_by_user_id via by-user-id GSI"
```

---

## Task 3: Backend — `PaperclipEventClient`

**Files:**
- Create: `apps/backend/core/services/paperclip_event_client.py`
- Test: `apps/backend/tests/unit/services/test_paperclip_event_client.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/unit/services/test_paperclip_event_client.py`:

```python
"""Unit tests for PaperclipEventClient.

Uses websockets.serve to spin up a fake Paperclip endpoint inside the
test process so we exercise the full WS roundtrip (handshake, frame,
parse, callback dispatch) without mocking websockets internals.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import pytest
import websockets

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")


async def _make_fake_server(handler):
    """Start a websockets server bound to a free localhost port."""
    server = await websockets.serve(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return server, f"ws://127.0.0.1:{port}"


@pytest.mark.asyncio
async def test_event_client_receives_and_dispatches_event():
    """Server sends one event; client invokes the on_event callback."""
    from core.services.paperclip_event_client import PaperclipEventClient

    received: list[dict] = []

    async def handler(ws):
        # Verify cookie header was sent.
        cookie = ws.request_headers.get("cookie") or ws.request_headers.get("Cookie")
        assert cookie == "test-session=abc"
        await ws.send(json.dumps({
            "id": 1, "companyId": "co_x", "type": "activity.logged",
            "createdAt": "2026-05-04T01:00:00Z", "payload": {"actor": "u1"},
        }))
        await ws.wait_closed()

    server, base_url = await _make_fake_server(handler)

    async def on_event(event: dict[str, Any]) -> None:
        received.append(event)

    client = PaperclipEventClient(
        url=base_url, cookie="test-session=abc", on_event=on_event,
    )
    await client.start()
    # Wait briefly for the event to flow.
    for _ in range(50):
        if received:
            break
        await asyncio.sleep(0.02)
    await client.close()
    server.close()
    await server.wait_closed()

    assert len(received) == 1
    assert received[0]["type"] == "activity.logged"
    assert received[0]["payload"] == {"actor": "u1"}


@pytest.mark.asyncio
async def test_event_client_emits_synthetic_stream_resumed_on_reconnect():
    """After server-side disconnect + client reconnect, on_event sees a
    synthetic ``{type: 'stream.resumed'}`` event so the broker can flush
    SWR caches. Spec § Reconnect semantics."""
    from core.services.paperclip_event_client import PaperclipEventClient

    received: list[dict] = []
    connect_count = 0

    async def handler(ws):
        nonlocal connect_count
        connect_count += 1
        if connect_count == 1:
            # First connection: send one real event then drop the socket.
            await ws.send(json.dumps({
                "id": 1, "companyId": "co_x", "type": "activity.logged",
                "createdAt": "2026-05-04T01:00:00Z", "payload": {},
            }))
            await ws.close()
        else:
            # Hold the second connection open until close().
            await ws.wait_closed()

    server, base_url = await _make_fake_server(handler)

    async def on_event(event: dict[str, Any]) -> None:
        received.append(event)

    client = PaperclipEventClient(
        url=base_url, cookie="c=1", on_event=on_event,
        reconnect_initial_delay=0.05,  # keep test fast
    )
    await client.start()
    # Wait for: real event from connect 1 + synthetic resumed from connect 2.
    for _ in range(100):
        if any(e.get("type") == "stream.resumed" for e in received):
            break
        await asyncio.sleep(0.05)
    await client.close()
    server.close()
    await server.wait_closed()

    types = [e["type"] for e in received]
    assert "activity.logged" in types
    assert "stream.resumed" in types
    # stream.resumed must come AFTER the real event (post-reconnect).
    assert types.index("stream.resumed") > types.index("activity.logged")


@pytest.mark.asyncio
async def test_event_client_close_stops_reconnect_loop():
    """After close(), no further reconnect attempts run even if the
    server keeps dropping connections."""
    from core.services.paperclip_event_client import PaperclipEventClient

    connect_count = 0

    async def handler(ws):
        nonlocal connect_count
        connect_count += 1
        await ws.close()

    server, base_url = await _make_fake_server(handler)

    async def on_event(event: dict[str, Any]) -> None:
        pass

    client = PaperclipEventClient(
        url=base_url, cookie="c=1", on_event=on_event,
        reconnect_initial_delay=0.05,
    )
    await client.start()
    await asyncio.sleep(0.2)  # let it reconnect a few times
    await client.close()
    count_at_close = connect_count
    await asyncio.sleep(0.3)  # if reconnect loop is still alive, count grows
    server.close()
    await server.wait_closed()

    # Allow at most 1 in-flight attempt after close (race tolerance).
    assert connect_count <= count_at_close + 1


@pytest.mark.asyncio
async def test_event_client_ignores_malformed_messages():
    """Non-JSON messages are logged + dropped, not crash the loop."""
    from core.services.paperclip_event_client import PaperclipEventClient

    received: list[dict] = []

    async def handler(ws):
        await ws.send("this is not json")
        await ws.send(json.dumps({
            "id": 2, "companyId": "co_x", "type": "agent.status",
            "createdAt": "2026-05-04T01:00:00Z", "payload": {"agentId": "a1"},
        }))
        await ws.wait_closed()

    server, base_url = await _make_fake_server(handler)

    async def on_event(event: dict[str, Any]) -> None:
        received.append(event)

    client = PaperclipEventClient(
        url=base_url, cookie="c=1", on_event=on_event,
    )
    await client.start()
    for _ in range(50):
        if received:
            break
        await asyncio.sleep(0.02)
    await client.close()
    server.close()
    await server.wait_closed()

    assert len(received) == 1
    assert received[0]["type"] == "agent.status"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && uv run pytest tests/unit/services/test_paperclip_event_client.py -v --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.services.paperclip_event_client'`.

- [ ] **Step 3: Implement `PaperclipEventClient`**

Create `apps/backend/core/services/paperclip_event_client.py`:

```python
"""Per-user persistent WebSocket client for Paperclip's live-events endpoint.

One instance owns one WS to ``/api/companies/{companyId}/events/ws``
authenticated with a Better-Auth session cookie. Reconnects with capped
exponential backoff. Emits each parsed event to a caller-supplied async
callback, plus a synthetic ``{type: "stream.resumed"}`` event after
every successful reconnect so the broker can flush downstream caches
(Paperclip has no replay cursor — see spec § Reconnect semantics).

Lifecycle: explicit ``start()`` opens the loop; ``close()`` stops it.
Owner (the broker) is responsible for calling ``close()`` when the
last subscriber leaves.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Any, Awaitable, Callable

import websockets
from websockets.exceptions import WebSocketException

logger = logging.getLogger(__name__)


# Backoff schedule: 1s, 2s, 4s, 8s, 16s, 30s (cap), with ±20% jitter.
# Matches the OpenClaw gateway client to keep operator mental model uniform.
_MAX_BACKOFF_SECONDS = 30.0
_MAX_RECONNECT_ATTEMPTS = 30  # ≈ 15 minutes of trying before giving up


class PaperclipEventClient:
    """Single backing connection from the backend to Paperclip's WS.

    Args:
        url: full ``ws://`` or ``wss://`` URL for the events endpoint.
        cookie: value of the ``Cookie:`` header (Better-Auth session).
        on_event: async callback invoked once per parsed event.
        reconnect_initial_delay: first-attempt backoff base (seconds).
            Tests override this to keep the suite fast.
    """

    def __init__(
        self,
        *,
        url: str,
        cookie: str,
        on_event: Callable[[dict[str, Any]], Awaitable[None]],
        reconnect_initial_delay: float = 1.0,
    ) -> None:
        self._url = url
        self._cookie = cookie
        self._on_event = on_event
        self._initial_delay = reconnect_initial_delay
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def start(self) -> None:
        """Begin the connect-loop in the background."""
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run())

    async def close(self) -> None:
        """Signal the connect-loop to stop and await its termination."""
        self._stop.set()
        task = self._task
        if task is None:
            return
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        self._task = None

    async def _run(self) -> None:
        """Connect/reconnect loop. Runs until ``close()`` or max attempts."""
        attempt = 0
        is_reconnect = False
        while not self._stop.is_set() and attempt < _MAX_RECONNECT_ATTEMPTS:
            try:
                async with websockets.connect(
                    self._url,
                    additional_headers={"Cookie": self._cookie},
                    open_timeout=10.0,
                    close_timeout=5.0,
                ) as ws:
                    self._connected = True
                    attempt = 0  # successful connect resets backoff
                    logger.info("paperclip event WS connected url=%s reconnect=%s", self._url, is_reconnect)
                    if is_reconnect:
                        # Synthetic event so the broker can flush downstream
                        # SWR caches (no upstream replay cursor exists).
                        try:
                            await self._on_event({"type": "stream.resumed"})
                        except Exception:
                            logger.exception("on_event raised on stream.resumed")
                    is_reconnect = True
                    await self._receive_loop(ws)
            except (WebSocketException, OSError) as e:
                logger.warning("paperclip event WS connect/recv error: %s", e)
            finally:
                self._connected = False

            if self._stop.is_set():
                return
            attempt += 1
            delay = self._backoff(attempt)
            logger.info("paperclip event WS reconnecting in %.1fs (attempt %d)", delay, attempt)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
                return  # stop fired during sleep
            except asyncio.TimeoutError:
                continue
        if attempt >= _MAX_RECONNECT_ATTEMPTS:
            logger.error("paperclip event WS giving up after %d attempts url=%s", attempt, self._url)

    async def _receive_loop(self, ws) -> None:
        """Read frames until the connection drops."""
        async for raw in ws:
            if self._stop.is_set():
                return
            try:
                event = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                logger.warning("paperclip event WS dropped malformed frame")
                continue
            try:
                await self._on_event(event)
            except Exception:
                logger.exception("on_event raised; continuing")

    def _backoff(self, attempt: int) -> float:
        """Capped exponential backoff with ±20% jitter."""
        base = min(self._initial_delay * (2 ** (attempt - 1)), _MAX_BACKOFF_SECONDS)
        jitter = base * 0.2 * (2 * random.random() - 1)
        return max(0.1, base + jitter)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/backend && uv run pytest tests/unit/services/test_paperclip_event_client.py -v --no-cov`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/services/paperclip_event_client.py apps/backend/tests/unit/services/test_paperclip_event_client.py
git commit -m "feat(teams): PaperclipEventClient — per-user backing WS to Paperclip events"
```

---

## Task 4: Backend — `TeamsEventBroker`

**Files:**
- Create: `apps/backend/core/services/teams_event_broker.py`
- Test: `apps/backend/tests/unit/services/test_teams_event_broker.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/unit/services/test_teams_event_broker.py`:

```python
"""Unit tests for TeamsEventBroker — the per-user fanout layer that owns
PaperclipEventClient instances and routes events to subscribed browser
connection IDs via the API Gateway Management API.
"""

from __future__ import annotations

import asyncio
import os
from typing import Awaitable, Callable
from unittest.mock import AsyncMock, MagicMock

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

    await fake_components["clients"][0].trigger({
        "id": 1, "companyId": "co_user_a", "type": "activity.logged",
        "createdAt": "2026-05-04T01:00:00Z", "payload": {"actor": "x"},
    })

    sent_to = [c.kwargs.get("connection_id") or c.args[0]
               for c in fake_components["mgmt"].send_message.call_args_list]
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

    await fake_components["clients"][0].trigger({
        "id": 1, "companyId": "co_user_a", "type": "agent.status",
        "createdAt": "2026-05-04T01:00:00Z", "payload": {},
    })

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && uv run pytest tests/unit/services/test_teams_event_broker.py -v --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.services.teams_event_broker'`.

- [ ] **Step 3: Implement `TeamsEventBroker`**

Create `apps/backend/core/services/teams_event_broker.py`:

```python
"""Process-wide singleton that brokers Paperclip live events to subscribed
browser WS connections.

Owns one ``PaperclipEventClient`` per *user* (not per browser tab). When
the last subscriber for a user disconnects, schedules a ``grace_seconds``
delayed teardown so reconnect storms (e.g. mobile network blip) don't
churn the upstream WS.

See spec: ``docs/superpowers/specs/2026-05-04-teams-realtime-design.md``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Protocol

logger = logging.getLogger(__name__)


_DEFAULT_GRACE_SECONDS = 30.0


class _Client(Protocol):
    """The narrow surface of PaperclipEventClient the broker depends on."""

    async def start(self) -> None: ...
    async def close(self) -> None: ...


ClientFactory = Callable[..., _Client]
"""Signature: (user_id, company_id, cookie, on_event) -> client.

Kept as a callable so tests can swap in a fake without monkeypatching."""


class TeamsEventBroker:
    """Routes Paperclip events to subscribed browser conn-IDs."""

    def __init__(
        self,
        *,
        client_factory: ClientFactory,
        management_api: Any,
        connection_service: Any,
        resolve_company_id: Callable[[str], Awaitable[str]],
        resolve_session_cookie: Callable[[str], Awaitable[str]],
        grace_seconds: float = _DEFAULT_GRACE_SECONDS,
    ) -> None:
        self._client_factory = client_factory
        self._mgmt = management_api
        self._conn_svc = connection_service
        self._resolve_company_id = resolve_company_id
        self._resolve_cookie = resolve_session_cookie
        self._grace_seconds = grace_seconds

        # State:
        self._clients: dict[str, _Client] = {}
        self._subscribers: dict[str, set[str]] = {}
        self._grace_tasks: dict[str, asyncio.Task[None]] = {}
        # Per-user lock prevents two near-simultaneous subscribes from
        # opening duplicate backing clients.
        self._locks: dict[str, asyncio.Lock] = {}

    def _user_lock(self, user_id: str) -> asyncio.Lock:
        lock = self._locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[user_id] = lock
        return lock

    async def subscribe(self, user_id: str, connection_id: str) -> None:
        """Register ``connection_id`` as a subscriber for ``user_id``.

        Idempotent — calling twice with the same conn-ID is a no-op.
        Cancels any pending teardown grace task.
        """
        async with self._user_lock(user_id):
            self._subscribers.setdefault(user_id, set()).add(connection_id)

            # Cancel pending grace teardown if one is scheduled.
            grace = self._grace_tasks.pop(user_id, None)
            if grace and not grace.done():
                grace.cancel()

            if user_id in self._clients:
                return

            try:
                company_id = await self._resolve_company_id(user_id)
                cookie = await self._resolve_cookie(user_id)
            except Exception:
                logger.exception("teams broker: cannot subscribe user=%s", user_id)
                self._subscribers[user_id].discard(connection_id)
                return

            async def _on_event(event: dict[str, Any]) -> None:
                await self._handle_event(user_id, event)

            client = self._client_factory(
                user_id=user_id, company_id=company_id, cookie=cookie, on_event=_on_event,
            )
            await client.start()
            self._clients[user_id] = client
            logger.info("teams broker: opened backing WS for user=%s company=%s", user_id, company_id)

    async def unsubscribe(self, user_id: str, connection_id: str) -> None:
        """Remove ``connection_id``; if subscriber set is empty, schedule
        teardown after ``grace_seconds``.
        """
        async with self._user_lock(user_id):
            subs = self._subscribers.get(user_id)
            if subs:
                subs.discard(connection_id)
            if subs:
                return  # still has subscribers
            self._subscribers.pop(user_id, None)

            if user_id in self._clients and user_id not in self._grace_tasks:
                self._grace_tasks[user_id] = asyncio.create_task(
                    self._grace_teardown(user_id),
                )

    async def _grace_teardown(self, user_id: str) -> None:
        try:
            await asyncio.sleep(self._grace_seconds)
        except asyncio.CancelledError:
            return
        async with self._user_lock(user_id):
            self._grace_tasks.pop(user_id, None)
            if self._subscribers.get(user_id):
                return  # someone resubscribed during the sleep race
            client = self._clients.pop(user_id, None)
        if client is not None:
            try:
                await client.close()
            except Exception:
                logger.exception("teams broker: close() failed for user=%s", user_id)
            logger.info("teams broker: closed backing WS for idle user=%s", user_id)

    async def _handle_event(self, user_id: str, event: dict[str, Any]) -> None:
        """Wrap and fan out one event to all of the user's connections."""
        wrapped = {
            "type": "event",
            "event": f"teams.{event.get('type', 'unknown')}",
            "payload": event.get("payload", {}),
        }
        # Forward upstream metadata if present.
        if "id" in event:
            wrapped["id"] = event["id"]
        if "createdAt" in event:
            wrapped["createdAt"] = event["createdAt"]

        try:
            conn_ids = await self._conn_svc.query_by_user_id(user_id)
        except Exception:
            logger.exception("teams broker: query_by_user_id failed user=%s", user_id)
            return

        for conn_id in conn_ids:
            try:
                ok = self._mgmt.send_message(conn_id, wrapped)
                if ok is False:
                    self._conn_svc.delete_connection(conn_id)
            except Exception:
                logger.exception("teams broker: send_message failed conn=%s", conn_id)

    async def shutdown(self) -> None:
        """Close every backing client + cancel grace tasks. Lifespan shutdown."""
        for task in self._grace_tasks.values():
            task.cancel()
        self._grace_tasks.clear()
        clients = list(self._clients.values())
        self._clients.clear()
        self._subscribers.clear()
        for client in clients:
            try:
                await client.close()
            except Exception:
                logger.exception("teams broker shutdown: close() failed")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/backend && uv run pytest tests/unit/services/test_teams_event_broker.py -v --no-cov`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/services/teams_event_broker.py apps/backend/tests/unit/services/test_teams_event_broker.py
git commit -m "feat(teams): TeamsEventBroker — per-user fanout for live events"
```

---

## Task 5: Backend — Wire broker into lifespan + provide a process-wide accessor

**Files:**
- Modify: `apps/backend/main.py`
- Create: `apps/backend/core/services/teams_event_broker_singleton.py` (small accessor module so routers and lifespan share one instance without a circular import)

- [ ] **Step 1: Create the singleton accessor**

Create `apps/backend/core/services/teams_event_broker_singleton.py`:

```python
"""Process-wide singleton accessor for the TeamsEventBroker.

Built once during FastAPI lifespan startup; consumed by
``routers/websocket_chat.py`` for ``teams.subscribe`` /
``teams.unsubscribe`` dispatch. Lives in its own module so the router
can import it without pulling in main.py (circular).
"""

from __future__ import annotations

from typing import Optional

from core.services.teams_event_broker import TeamsEventBroker

_singleton: Optional[TeamsEventBroker] = None


def set_broker(broker: TeamsEventBroker | None) -> None:
    """Called by main.py during startup/shutdown."""
    global _singleton
    _singleton = broker


def get_broker() -> TeamsEventBroker | None:
    """Return the live broker, or None if startup hasn't happened yet
    (e.g. some unit-test bootstrapping)."""
    return _singleton
```

- [ ] **Step 2: Wire startup/shutdown in `main.py`**

In `apps/backend/main.py`, modify the `lifespan` function (currently at lines 220-253) to start/stop the broker. Add the broker construction between `worker_task = asyncio.create_task(run_scheduled_worker())` and the `gauge_task` line. Show the full updated `lifespan`:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    logger.info("Starting application...")
    await startup_containers()
    await _resume_provisioning_transitions()
    worker_task = asyncio.create_task(run_scheduled_worker())

    # Teams event broker — proxies Paperclip's per-company live-events WS
    # to subscribed browser tabs via API Gateway Management API. Started
    # after the gateway pool (so management_api singleton is initialized)
    # but before anything that depends on its API.
    broker = await _build_teams_event_broker()
    if broker is not None:
        from core.services import teams_event_broker_singleton

        teams_event_broker_singleton.set_broker(broker)

    gauge_task = asyncio.create_task(_running_count_gauge_loop())

    # Register background tasks so /admin/system/health can surface their state.
    from core.services import system_health

    system_health.BACKGROUND_TASKS["scheduled_worker"] = worker_task
    system_health.BACKGROUND_TASKS["running_gauges"] = gauge_task

    yield

    # Shutdown
    logger.info("Shutting down application...")
    system_health.BACKGROUND_TASKS.clear()
    gauge_task.cancel()
    worker_task.cancel()
    try:
        await gauge_task
    except asyncio.CancelledError:
        pass
    try:
        await worker_task
    except asyncio.CancelledError:
        pass

    if broker is not None:
        from core.services import teams_event_broker_singleton

        await broker.shutdown()
        teams_event_broker_singleton.set_broker(None)

    await shutdown_containers()
```

Then add `_build_teams_event_broker` near the top of the file (after the other helper functions, around line 218 right before the `lifespan` definition):

```python
async def _build_teams_event_broker():
    """Construct the singleton TeamsEventBroker used by /ws/message.

    Returns None when the dependencies aren't configured (e.g. local
    dev without Paperclip running) — the broker is best-effort and
    /teams continues to work via REST without realtime updates.
    """
    try:
        import os

        from core.repositories.paperclip_repo import PaperclipRepo
        from core.services.connection_service import ConnectionService
        from core.services.management_api_client import ManagementApiClient
        from core.services.paperclip_event_client import PaperclipEventClient
        from core.services.teams_event_broker import TeamsEventBroker

        # Best-effort: if the Paperclip env isn't configured (no internal
        # URL), don't try to start the broker — /teams REST still works,
        # just without live updates.
        paperclip_url = (settings.PAPERCLIP_INTERNAL_URL or "").strip()
        if not paperclip_url:
            logger.info("teams broker: PAPERCLIP_INTERNAL_URL unset; skipping startup")
            return None

        # Resolve ws:// / wss:// from the http(s):// internal URL.
        if paperclip_url.startswith("https://"):
            ws_base = "wss://" + paperclip_url[len("https://") :]
        elif paperclip_url.startswith("http://"):
            ws_base = "ws://" + paperclip_url[len("http://") :]
        else:
            ws_base = paperclip_url
        ws_base = ws_base.rstrip("/")

        repo = PaperclipRepo(table_name="paperclip-companies")
        conn_svc = ConnectionService()
        mgmt_api = ManagementApiClient()

        # Per-user dependencies share the existing helpers from agents.py.
        from routers.teams.agents import _admin, _resolve_user_email
        from core.services.paperclip_user_session import get_user_session_cookie

        async def resolve_company_id(user_id: str) -> str:
            company = await repo.get(user_id)
            if company is None:
                raise RuntimeError(f"no paperclip company for user {user_id}")
            return company.company_id

        async def resolve_session_cookie(user_id: str) -> str:
            return await get_user_session_cookie(
                user_id=user_id,
                repo=repo,
                admin_client=_admin(),
                clerk_email_resolver=_resolve_user_email,
            )

        def client_factory(*, user_id: str, company_id: str, cookie: str, on_event):
            return PaperclipEventClient(
                url=f"{ws_base}/api/companies/{company_id}/events/ws",
                cookie=cookie,
                on_event=on_event,
            )

        broker = TeamsEventBroker(
            client_factory=client_factory,
            management_api=mgmt_api,
            connection_service=conn_svc,
            resolve_company_id=resolve_company_id,
            resolve_session_cookie=resolve_session_cookie,
        )
        logger.info("teams broker: started; ws_base=%s", ws_base)
        return broker
    except Exception:
        logger.exception("teams broker: startup failed; /teams will run without live updates")
        return None
```

- [ ] **Step 3: Verify backend still imports + lifespan symbols resolve**

Run: `cd apps/backend && uv run python -c "from main import lifespan, _build_teams_event_broker; print('ok')"`
Expected: prints `ok` with no errors.

- [ ] **Step 4: Commit**

```bash
git add apps/backend/main.py apps/backend/core/services/teams_event_broker_singleton.py
git commit -m "feat(teams): wire TeamsEventBroker into FastAPI lifespan"
```

---

## Task 6: Backend — `teams.subscribe` / `teams.unsubscribe` routes

**Files:**
- Modify: `apps/backend/routers/websocket_chat.py:226-411` (the `ws_message` dispatcher)
- Test: `apps/backend/tests/unit/routers/test_websocket_chat_teams.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/unit/routers/test_websocket_chat_teams.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && uv run pytest tests/unit/routers/test_websocket_chat_teams.py -v --no-cov`
Expected: FAIL — first three tests fail because the dispatcher doesn't yet handle `teams.subscribe` / `teams.unsubscribe`. The fourth (`ping`) should already pass.

- [ ] **Step 3: Add the dispatch branches**

In `apps/backend/routers/websocket_chat.py`, add this block immediately AFTER the `ping` handler (right after the `if msg_type == "ping":` block, around line 230). Do NOT remove or modify any existing branches.

```python
    # Teams BFF realtime: browser opts into / out of Paperclip event fanout.
    # Best-effort — if the broker singleton isn't configured (local dev
    # without Paperclip env), 200 silently and /teams just runs without
    # live updates.
    if msg_type in ("teams.subscribe", "teams.unsubscribe"):
        from core.services import teams_event_broker_singleton

        broker = teams_event_broker_singleton.get_broker()
        if broker is not None:
            try:
                if msg_type == "teams.subscribe":
                    await broker.subscribe(user_id, x_connection_id)
                else:
                    await broker.unsubscribe(user_id, x_connection_id)
            except Exception:
                logger.exception(
                    "teams broker dispatch failed type=%s user=%s conn=%s",
                    msg_type, user_id,
                    x_connection_id[:12] if x_connection_id else "?",
                )
        return Response(status_code=200)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/backend && uv run pytest tests/unit/routers/test_websocket_chat_teams.py -v --no-cov`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/routers/websocket_chat.py apps/backend/tests/unit/routers/test_websocket_chat_teams.py
git commit -m "feat(teams): /ws/message dispatch for teams.subscribe and teams.unsubscribe"
```

---

## Task 7: Frontend — Wrap `/teams` in `GatewayProvider`

**Files:**
- Modify: `apps/frontend/src/app/teams/layout.tsx`

- [ ] **Step 1: Edit the route layout**

Replace the contents of `apps/frontend/src/app/teams/layout.tsx` with:

```tsx
import { GatewayProvider } from "@/hooks/useGateway";
import { TeamsLayout } from "@/components/teams/TeamsLayout";

export default function Layout({ children }: { children: React.ReactNode }) {
  // GatewayProvider opens the WS to API Gateway lazily — already used by /chat
  // and MyChannelsSection. /teams needs it too so TeamsEventsProvider can send
  // teams.subscribe and listen for live events.
  return (
    <GatewayProvider>
      <TeamsLayout>{children}</TeamsLayout>
    </GatewayProvider>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd apps/frontend && pnpm exec tsc --noEmit`
Expected: no output (compiles clean).

- [ ] **Step 3: Verify existing teams panel tests still pass**

Run: `cd apps/frontend && pnpm test -- DashboardPanel`
Expected: existing DashboardPanel test still passes (it mocks useTeamsApi, doesn't depend on GatewayProvider).

- [ ] **Step 4: Commit**

```bash
git add apps/frontend/src/app/teams/layout.tsx
git commit -m "feat(teams): wrap /teams route in GatewayProvider"
```

---

## Task 8: Frontend — `TeamsEventsProvider` + mount in `TeamsLayout`

**Files:**
- Create: `apps/frontend/src/components/teams/TeamsEventsProvider.tsx`
- Modify: `apps/frontend/src/components/teams/TeamsLayout.tsx`
- Test: `apps/frontend/src/__tests__/teams/TeamsEventsProvider.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/teams/TeamsEventsProvider.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, act } from "@testing-library/react";
import { useEffect } from "react";

// Module-level handlers — captured from the mocked useGateway so the
// test can drive synthetic events into the provider.
let eventHandler: ((event: string, data: unknown) => void) | null = null;
const sendMock = vi.fn();
const setIsConnected = vi.fn();

const gatewayState = { isConnected: false };

vi.mock("@/hooks/useGateway", () => ({
  useGateway: () => ({
    isConnected: gatewayState.isConnected,
    send: sendMock,
    onEvent: (handler: (event: string, data: unknown) => void) => {
      eventHandler = handler;
      return () => {
        eventHandler = null;
      };
    },
  }),
}));

const mutateMock = vi.fn();
vi.mock("swr", () => ({
  useSWRConfig: () => ({ mutate: mutateMock }),
}));

import { TeamsEventsProvider } from "@/components/teams/TeamsEventsProvider";

beforeEach(() => {
  sendMock.mockReset();
  mutateMock.mockReset();
  setIsConnected.mockReset();
  eventHandler = null;
  gatewayState.isConnected = false;
});

describe("TeamsEventsProvider", () => {
  it("sends teams.subscribe when connected", async () => {
    gatewayState.isConnected = true;
    render(<TeamsEventsProvider><div /></TeamsEventsProvider>);
    expect(sendMock).toHaveBeenCalledWith({ type: "teams.subscribe" });
  });

  it("invalidates inbox + dashboard + activity + issues on teams.activity.logged", async () => {
    gatewayState.isConnected = true;
    render(<TeamsEventsProvider><div /></TeamsEventsProvider>);
    expect(eventHandler).not.toBeNull();

    act(() => {
      eventHandler!("teams.activity.logged", { actor: "u1" });
    });

    const keys = mutateMock.mock.calls.map((c) => c[0]);
    expect(keys).toEqual(expect.arrayContaining([
      "/teams/dashboard", "/teams/activity", "/teams/inbox", "/teams/issues",
    ]));
  });

  it("invalidates dashboard + agents on teams.agent.status", () => {
    gatewayState.isConnected = true;
    render(<TeamsEventsProvider><div /></TeamsEventsProvider>);
    act(() => {
      eventHandler!("teams.agent.status", {});
    });
    const keys = mutateMock.mock.calls.map((c) => c[0]);
    expect(keys).toEqual(expect.arrayContaining(["/teams/dashboard", "/teams/agents"]));
  });

  it("invalidates dashboard + inbox on teams.heartbeat.run.queued", () => {
    gatewayState.isConnected = true;
    render(<TeamsEventsProvider><div /></TeamsEventsProvider>);
    act(() => {
      eventHandler!("teams.heartbeat.run.queued", {});
    });
    const keys = mutateMock.mock.calls.map((c) => c[0]);
    expect(keys).toEqual(expect.arrayContaining(["/teams/dashboard", "/teams/inbox"]));
  });

  it("ignores teams.plugin.* events (no UI bound in v1)", () => {
    gatewayState.isConnected = true;
    render(<TeamsEventsProvider><div /></TeamsEventsProvider>);
    act(() => {
      eventHandler!("teams.plugin.ui.updated", {});
      eventHandler!("teams.plugin.worker.crashed", {});
    });
    expect(mutateMock).not.toHaveBeenCalled();
  });

  it("invalidates every distinct mapped key on teams.stream.resumed", () => {
    gatewayState.isConnected = true;
    render(<TeamsEventsProvider><div /></TeamsEventsProvider>);
    act(() => {
      eventHandler!("teams.stream.resumed", {});
    });
    const keys = mutateMock.mock.calls.map((c) => c[0]);
    // Must include each unique key from the event map.
    expect(keys).toEqual(expect.arrayContaining([
      "/teams/dashboard", "/teams/activity", "/teams/inbox", "/teams/issues", "/teams/agents",
    ]));
  });

  it("re-subscribes and invalidates on isConnected false→true transition", () => {
    gatewayState.isConnected = false;
    const { rerender } = render(<TeamsEventsProvider><div /></TeamsEventsProvider>);
    expect(sendMock).not.toHaveBeenCalled();

    gatewayState.isConnected = true;
    rerender(<TeamsEventsProvider><div /></TeamsEventsProvider>);
    expect(sendMock).toHaveBeenCalledWith({ type: "teams.subscribe" });
    // And ALL mapped keys are invalidated as a "no backfill" safety net.
    const keys = mutateMock.mock.calls.map((c) => c[0]);
    expect(keys).toEqual(expect.arrayContaining(["/teams/dashboard", "/teams/inbox"]));
  });

  it("sends teams.unsubscribe on unmount", () => {
    gatewayState.isConnected = true;
    const { unmount } = render(<TeamsEventsProvider><div /></TeamsEventsProvider>);
    sendMock.mockClear();
    unmount();
    expect(sendMock).toHaveBeenCalledWith({ type: "teams.unsubscribe" });
  });

  it("ignores non-teams events (e.g. an OpenClaw event leaking through)", () => {
    gatewayState.isConnected = true;
    render(<TeamsEventsProvider><div /></TeamsEventsProvider>);
    act(() => {
      eventHandler!("agent_chat", {});
      eventHandler!("openclaw.something", {});
    });
    expect(mutateMock).not.toHaveBeenCalled();
  });
});

// Coverage-only export to suppress unused-import warning on useEffect.
const _u = useEffect;
void _u;
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/frontend && pnpm test -- TeamsEventsProvider`
Expected: tests FAIL with `Cannot find module '@/components/teams/TeamsEventsProvider'`.

- [ ] **Step 3: Implement `TeamsEventsProvider`**

Create `apps/frontend/src/components/teams/TeamsEventsProvider.tsx`:

```tsx
"use client";

import { useEffect, useRef } from "react";
import { useSWRConfig } from "swr";
import { useGateway } from "@/hooks/useGateway";

/**
 * Mounts inside TeamsLayout (which is inside GatewayProvider). Subscribes
 * to Paperclip live events forwarded by the BFF and invalidates SWR cache
 * keys per event type so panels rerender automatically.
 *
 * Spec: docs/superpowers/specs/2026-05-04-teams-realtime-design.md
 *
 * Pattern mirrors Paperclip's own LiveUpdatesProvider — a single mount
 * point owns all realtime invalidation; panels themselves stay free of
 * realtime concerns.
 */

const ALL_KEYS = [
  "/teams/dashboard",
  "/teams/activity",
  "/teams/inbox",
  "/teams/issues",
  "/teams/agents",
];

const EVENT_KEY_MAP: Record<string, string[]> = {
  "teams.activity.logged": [
    "/teams/dashboard", "/teams/activity", "/teams/inbox", "/teams/issues",
  ],
  "teams.agent.status": ["/teams/dashboard", "/teams/agents"],
  "teams.heartbeat.run.queued": ["/teams/dashboard", "/teams/inbox"],
  "teams.heartbeat.run.status": ["/teams/dashboard", "/teams/inbox"],
  // Run-event/log only matter when run-detail is open. SWR mutate on a
  // path-prefix is not natively supported; the panels for those routes
  // can subscribe themselves later. For now, no global invalidation.
  "teams.heartbeat.run.event": [],
  "teams.heartbeat.run.log": [],
};

export function TeamsEventsProvider({ children }: { children: React.ReactNode }) {
  const { isConnected, send, onEvent } = useGateway();
  const { mutate } = useSWRConfig();
  const wasConnectedRef = useRef(false);

  // (re)subscribe + full invalidation on connect / reconnect.
  useEffect(() => {
    if (!isConnected) {
      wasConnectedRef.current = false;
      return;
    }
    send({ type: "teams.subscribe" });
    if (wasConnectedRef.current === false) {
      // Reconnect path (or first connect): refetch everything because
      // Paperclip's WS has no replay cursor and we may have missed events.
      for (const key of ALL_KEYS) mutate(key);
    }
    wasConnectedRef.current = true;
  }, [isConnected, send, mutate]);

  // Wire event listener.
  useEffect(() => {
    const unsub = onEvent((event, _data) => {
      if (!event.startsWith("teams.")) return;
      if (event === "teams.stream.resumed") {
        for (const key of ALL_KEYS) mutate(key);
        return;
      }
      const keys = EVENT_KEY_MAP[event];
      if (!keys || keys.length === 0) return;
      for (const key of keys) mutate(key);
    });
    return () => {
      unsub();
    };
  }, [onEvent, mutate]);

  // Best-effort unsubscribe on unmount.
  useEffect(() => {
    return () => {
      send({ type: "teams.unsubscribe" });
    };
  }, [send]);

  return <>{children}</>;
}
```

- [ ] **Step 4: Mount the provider in `TeamsLayout`**

In `apps/frontend/src/components/teams/TeamsLayout.tsx`, replace the file contents with:

```tsx
"use client";

import { useTeamsWorkspaceStatus } from "@/hooks/useTeamsApi";
import { TeamsEventsProvider } from "./TeamsEventsProvider";
import { TeamsSidebar } from "./TeamsSidebar";

export function TeamsLayout({ children }: { children: React.ReactNode }) {
  const status = useTeamsWorkspaceStatus();

  return (
    <div className="flex h-screen overflow-hidden">
      <TeamsSidebar />
      <main className="flex-1 overflow-auto">
        {status.kind === "provisioning" ? (
          <ProvisioningOverlay />
        ) : status.kind === "subscribe_required" ? (
          <SubscribeOverlay />
        ) : status.kind === "error" ? (
          <ErrorOverlay error={status.error} />
        ) : (
          <TeamsEventsProvider>{children}</TeamsEventsProvider>
        )}
      </main>
    </div>
  );
}

function ProvisioningOverlay() {
  return (
    <div className="p-8">
      <h1 className="text-2xl font-semibold mb-2">Setting up your Teams workspace…</h1>
      <p className="text-zinc-600">
        This usually takes about 30 seconds. The page will refresh automatically.
      </p>
    </div>
  );
}

function SubscribeOverlay() {
  return (
    <div className="p-8">
      <h1 className="text-2xl font-semibold mb-2">Subscribe to enable Teams</h1>
      <p className="text-zinc-600">
        Teams runs on top of your agent container. Start a subscription from the chat
        page first, then come back.
      </p>
    </div>
  );
}

function ErrorOverlay({ error }: { error: Error }) {
  return (
    <div className="p-8 text-red-600">Error: {String(error.message ?? error)}</div>
  );
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd apps/frontend && pnpm test -- TeamsEventsProvider`
Expected: 9 passed.

- [ ] **Step 6: Verify existing teams tests still pass**

Run: `cd apps/frontend && pnpm test -- teams`
Expected: every existing teams panel test still passes.

- [ ] **Step 7: Commit**

```bash
git add apps/frontend/src/components/teams/TeamsEventsProvider.tsx apps/frontend/src/components/teams/TeamsLayout.tsx apps/frontend/src/__tests__/teams/TeamsEventsProvider.test.tsx
git commit -m "feat(teams): TeamsEventsProvider — drive SWR invalidations from gateway events"
```

---

## Task 9: Final verification — full test suites + lint

This is the only place we run the full suites; per project memory, individual tasks only run their own targeted tests.

- [ ] **Step 1: Full backend test suite**

Run: `cd apps/backend && uv run pytest -q`
Expected: all tests pass. If any fail, fix the regression — the realtime work shouldn't have changed any unrelated surface.

- [ ] **Step 2: Full frontend test suite**

Run: `cd apps/frontend && pnpm test`
Expected: all unit tests pass. Pre-existing failures in BotSetupWizard / MyChannelsSection / AgentChannelsSection / CreditsPanel that we observed earlier in this session are NOT regressions from this work — they should still pass-or-fail in the same pattern as before.

- [ ] **Step 3: Frontend lint**

Run: `cd apps/frontend && pnpm lint`
Expected: 0 errors. The pre-existing warnings (`no-img-element`, `react-hooks/exhaustive-deps`) are unchanged; no new warnings introduced by this work.

- [ ] **Step 4: CDK synth (sanity)**

Run: `cd apps/infra && pnpm cdk synth dev/isol8-dev/api 2>&1 | grep -B 2 -A 5 "by-user-id" | head -20`
Expected: `by-user-id` GSI appears in the synthesized CloudFormation, with `KEYS_ONLY` projection.

- [ ] **Step 5: Push and open PR**

```bash
git push -u origin spec/teams-realtime
gh pr create --title "feat(teams): realtime updates — Paperclip WS broker + SWR invalidation provider" --body "$(cat <<'PRBODY'
## Summary

Implements [sub-project #1 of the teams UI parity roadmap](docs/superpowers/specs/2026-05-04-teams-ui-parity-roadmap.md): live updates so /teams panels refresh automatically when Paperclip emits events.

Spec: \`docs/superpowers/specs/2026-05-04-teams-realtime-design.md\`
Plan: \`docs/superpowers/plans/2026-05-04-teams-realtime.md\`

## What's in here

**Backend**
- \`PaperclipEventClient\`: per-user persistent WS to Paperclip's \`/api/companies/{id}/events/ws\` with reconnect + synthetic resume event
- \`TeamsEventBroker\`: process-wide singleton, per-user fanout to API Gateway Management API, 30s grace teardown, race-safe locks
- \`/ws/message\` dispatcher: new \`teams.subscribe\` / \`teams.unsubscribe\` types
- Lifespan startup/shutdown integration in main.py

**Frontend**
- \`TeamsLayout\` route now wraps in \`GatewayProvider\` (was only mounted on /chat before)
- \`TeamsEventsProvider\` mounted inside layout: drives SWR invalidations from gateway events with central event→key map, also invalidates all keys on reconnect (no-backfill safety)

**Infra**
- \`by-user-id\` GSI on \`ws-connections\` table (KEYS_ONLY) so broker fanout is O(1) instead of full-table scan
- IAM policy on backend service grants \`Query\` on the new index ARN

## Test plan

- [x] Backend unit: 4 PaperclipEventClient + 8 TeamsEventBroker + 4 dispatcher + 2 ConnectionService.query_by_user_id
- [x] Frontend unit: 9 TeamsEventsProvider cases
- [x] CDK synth shows by-user-id GSI present
- [x] No regressions in existing teams panel tests
- [ ] Deploy to dev, open /teams/dashboard, trigger a Paperclip event from a separate REST call, verify dashboard refreshes within ~1s

🤖 Generated with [Claude Code](https://claude.com/claude-code)
PRBODY
)"
```

Expected: prints the new PR URL.

---

## Implementation notes for subagents

**Per-task execution model (per project memory: subagent-driven-development).** Each task is a single subagent dispatch. The subagent:

1. Reads its task section in full + the spec section it implements
2. Writes the test FIRST (red), runs it (verifies red), implements (green), runs again (verifies green), commits
3. Does NOT run the full test suite — only its own targeted file
4. Reports DONE and the controller dispatches the spec-reviewer + code-quality-reviewer subagents

**Use opus for every subagent** (per project memory `feedback_always_best_model.md`).

**Branch:** all tasks land on `spec/teams-realtime` (the branch this plan lives on).

**Final task (Task 9) is the gate:** after all per-task subagents finish + their reviews are clean, the controller (or a final subagent) runs the full suites + opens the PR.

## Out-of-scope reminders (DO NOT IMPLEMENT)

These are explicitly deferred per the spec — adding them in this PR will trigger spec-reviewer rejection:

- **`teams.stream.degraded` UI banner.** The spec defers this until real users hit it; emit the synthetic event server-side if you must, but no frontend rendering of "Live updates paused".
- **Run-detail panel auto-poll for `heartbeat.run.event` / `heartbeat.run.log`.** The map intentionally returns `[]` for those event types in v1; run-detail panels can self-subscribe in a follow-up PR.
- **Caching the per-user Paperclip session cookie.** Per-request mint is fine for v1.
- **Inline cache mutation / optimistic updates.** Always invalidate + refetch.
