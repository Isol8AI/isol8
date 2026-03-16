# Unified WebSocket Architecture — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace HTTP-polling RPC with persistent WebSocket connections that proxy OpenClaw's native req/res/event protocol through the existing API Gateway WebSocket.

**Architecture:** Backend holds one persistent WebSocket per active user to their OpenClaw gateway (GatewayConnectionPool). Frontend sends `{type: "req"}` messages over its existing API Gateway WebSocket. Backend proxies them to the gateway and forwards `res`/`event` messages back via Management API. Chat streaming (`agent_chat`/`chunk`/`done`) continues through its existing code path unchanged.

**Tech Stack:** Python `websockets` library (already used), asyncio Futures for request/response matching, React Context for shared WebSocket state, SWR for caching.

**Design doc:** `docs/plans/2026-03-01-unified-websocket-design.md`

---

## Task 1: Backend — GatewayConnection + GatewayConnectionPool

**Files:**
- Create: `backend/core/gateway/connection_pool.py`
- Create: `backend/tests/unit/core/test_connection_pool.py`

This task creates both the implementation and tests. Tests are NOT run until Task 10.

**Step 1: Write the implementation**

```python
# backend/core/gateway/connection_pool.py
"""
Persistent WebSocket connection pool to OpenClaw gateway containers.

Maintains one WebSocket per active user. Proxies OpenClaw's native
req/res/event protocol. Background reader task handles incoming messages:
- type=res: resolves pending RPC Futures
- type=event: forwards to user's frontend connections via Management API
"""

import asyncio
import json
import logging
import uuid
from typing import Any, Dict, Optional, Set

from websockets import connect as ws_connect

from core.containers.ecs_manager import GATEWAY_PORT

logger = logging.getLogger(__name__)

_HANDSHAKE_TIMEOUT = 10  # seconds
_RPC_TIMEOUT = 30  # seconds
_RECONNECT_DELAYS = [1, 2, 4]  # exponential backoff
_GRACE_PERIOD = 30  # seconds before closing idle connection


class GatewayConnection:
    """Single persistent WebSocket to a user's OpenClaw gateway."""

    def __init__(
        self,
        user_id: str,
        ip: str,
        token: str,
        management_api: Any,
    ) -> None:
        self.user_id = user_id
        self.ip = ip
        self.token = token
        self._management_api = management_api
        self._ws: Any = None
        self._reader_task: Optional[asyncio.Task] = None
        self._pending_rpcs: Dict[str, asyncio.Future] = {}
        self._frontend_connections: Set[str] = set()
        self._closed = False
        self._grace_task: Optional[asyncio.Task] = None

    @property
    def is_connected(self) -> bool:
        return self._ws is not None and not getattr(self._ws, "closed", True)

    async def connect(self) -> None:
        """Open WebSocket, complete OpenClaw handshake, start reader."""
        uri = f"ws://{self.ip}:{GATEWAY_PORT}"
        self._ws = await ws_connect(uri, open_timeout=_HANDSHAKE_TIMEOUT, close_timeout=5)
        await self._handshake()
        self._reader_task = asyncio.create_task(self._reader_loop())
        logger.info("Gateway connection established for user %s at %s", self.user_id, self.ip)

    async def _handshake(self) -> None:
        """Complete OpenClaw connect handshake."""
        # Step 1: receive connect.challenge
        raw = await asyncio.wait_for(self._ws.recv(), timeout=_HANDSHAKE_TIMEOUT)
        challenge = json.loads(raw)
        if challenge.get("event") != "connect.challenge":
            raise RuntimeError(f"Expected connect.challenge, got: {challenge.get('event', 'unknown')}")

        # Step 2: send connect
        connect_msg = {
            "type": "req",
            "id": str(uuid.uuid4()),
            "method": "connect",
            "params": {
                "minProtocol": 3,
                "maxProtocol": 3,
                "client": {"id": "isol8-pool", "version": "1.0.0", "platform": "linux", "mode": "cli"},
                "role": "operator",
                "scopes": ["operator.admin"],
                "auth": {"token": self.token},
            },
        }
        await self._ws.send(json.dumps(connect_msg))

        # Step 3: verify hello-ok
        resp_raw = await asyncio.wait_for(self._ws.recv(), timeout=_HANDSHAKE_TIMEOUT)
        resp = json.loads(resp_raw)
        if not resp.get("ok"):
            err = resp.get("error", {}).get("message", "unknown error")
            raise RuntimeError(f"Gateway connect failed: {err}")

    async def send_rpc(self, req_id: str, method: str, params: dict) -> None:
        """Send {type: req} on the gateway WebSocket."""
        msg = {"type": "req", "id": req_id, "method": method, "params": params or {}}
        await self._ws.send(json.dumps(msg))

    async def wait_for_response(self, req_id: str, timeout: float = _RPC_TIMEOUT) -> Any:
        """Wait for the matching res message. Returns payload or raises."""
        future = asyncio.get_event_loop().create_future()
        self._pending_rpcs[req_id] = future
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending_rpcs.pop(req_id, None)
            raise
        finally:
            self._pending_rpcs.pop(req_id, None)

    def _handle_message(self, data: dict) -> None:
        """Route an incoming gateway message."""
        msg_type = data.get("type")

        if msg_type == "res":
            req_id = data.get("id")
            future = self._pending_rpcs.get(req_id)
            if future and not future.done():
                if data.get("ok"):
                    future.set_result(data.get("payload", {}))
                else:
                    err_msg = data.get("error", {}).get("message", "RPC call rejected")
                    future.set_exception(RuntimeError(err_msg))
            return

        if msg_type == "event":
            # Forward to all frontend connections
            for conn_id in list(self._frontend_connections):
                try:
                    self._management_api.send_message(conn_id, data)
                except Exception:
                    logger.warning("Failed to forward event to %s", conn_id)
            return

    async def _reader_loop(self) -> None:
        """Background task: read all messages from gateway WebSocket."""
        try:
            async for raw in self._ws:
                try:
                    data = json.loads(raw)
                    self._handle_message(data)
                except json.JSONDecodeError:
                    logger.warning("Non-JSON message from gateway for user %s", self.user_id)
        except asyncio.CancelledError:
            return
        except Exception as e:
            if self._closed:
                return
            logger.error("Gateway reader loop error for user %s: %s", self.user_id, e)
            # Reject all pending RPCs
            for req_id, future in list(self._pending_rpcs.items()):
                if not future.done():
                    future.set_exception(RuntimeError("Gateway connection lost"))
            self._pending_rpcs.clear()

    def add_frontend_connection(self, connection_id: str) -> None:
        """Register a frontend WebSocket connection for event forwarding."""
        self._frontend_connections.add(connection_id)
        if self._grace_task and not self._grace_task.done():
            self._grace_task.cancel()
            self._grace_task = None

    def remove_frontend_connection(self, connection_id: str) -> None:
        """Unregister a frontend connection."""
        self._frontend_connections.discard(connection_id)

    @property
    def has_frontend_connections(self) -> bool:
        return len(self._frontend_connections) > 0

    async def close(self) -> None:
        """Shut down: cancel reader, close WebSocket."""
        self._closed = True
        if self._grace_task and not self._grace_task.done():
            self._grace_task.cancel()
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            await self._ws.close()
        # Reject pending RPCs
        for req_id, future in list(self._pending_rpcs.items()):
            if not future.done():
                future.set_exception(RuntimeError("Connection closed"))
        self._pending_rpcs.clear()


class GatewayConnectionPool:
    """Pool of persistent gateway connections, one per active user."""

    def __init__(self, management_api: Any) -> None:
        self._management_api = management_api
        self._connections: Dict[str, GatewayConnection] = {}
        self._frontend_connections: Dict[str, Set[str]] = {}  # user_id -> set of conn_ids
        self._lock = asyncio.Lock()
        self._grace_tasks: Dict[str, asyncio.Task] = {}

    async def _create_connection(self, user_id: str, ip: str, token: str) -> GatewayConnection:
        """Create and connect a new GatewayConnection."""
        conn = GatewayConnection(
            user_id=user_id,
            ip=ip,
            token=token,
            management_api=self._management_api,
        )
        # Transfer any already-registered frontend connections
        for fc in self._frontend_connections.get(user_id, set()):
            conn.add_frontend_connection(fc)
        await conn.connect()
        self._connections[user_id] = conn
        return conn

    async def send_rpc(
        self,
        user_id: str,
        req_id: str,
        method: str,
        params: dict,
        ip: str,
        token: str,
    ) -> Any:
        """Send RPC via persistent connection (create if needed)."""
        async with self._lock:
            conn = self._connections.get(user_id)
            if conn is None or not conn.is_connected:
                conn = await self._create_connection(user_id, ip, token)

        await conn.send_rpc(req_id, method, params)
        return await conn.wait_for_response(req_id)

    def add_frontend_connection(self, user_id: str, connection_id: str) -> None:
        """Register a frontend WS connection for event forwarding."""
        if user_id not in self._frontend_connections:
            self._frontend_connections[user_id] = set()
        self._frontend_connections[user_id].add(connection_id)

        # Also register on existing gateway connection
        conn = self._connections.get(user_id)
        if conn:
            conn.add_frontend_connection(connection_id)

        # Cancel grace period if one is running
        grace = self._grace_tasks.pop(user_id, None)
        if grace and not grace.done():
            grace.cancel()

    def remove_frontend_connection(self, user_id: str, connection_id: str) -> None:
        """Unregister a frontend connection. Start grace period if none remain."""
        fcs = self._frontend_connections.get(user_id)
        if fcs:
            fcs.discard(connection_id)

        conn = self._connections.get(user_id)
        if conn:
            conn.remove_frontend_connection(connection_id)

        # Start grace period if no frontend connections remain
        if not fcs and user_id in self._connections:
            self._grace_tasks[user_id] = asyncio.create_task(
                self._grace_close(user_id)
            )

    async def _grace_close(self, user_id: str) -> None:
        """Wait grace period, then close gateway connection if still idle."""
        try:
            await asyncio.sleep(_GRACE_PERIOD)
            fcs = self._frontend_connections.get(user_id, set())
            if not fcs:
                await self.close_user(user_id)
        except asyncio.CancelledError:
            pass

    async def close_user(self, user_id: str) -> None:
        """Close gateway connection for a user."""
        conn = self._connections.pop(user_id, None)
        if conn:
            await conn.close()
        self._frontend_connections.pop(user_id, None)
        self._grace_tasks.pop(user_id, None)

    async def close_all(self) -> None:
        """Shutdown: close all connections."""
        for user_id in list(self._connections.keys()):
            await self.close_user(user_id)
```

**Step 2: Write the tests**

```python
# backend/tests/unit/core/test_connection_pool.py
"""Unit tests for GatewayConnectionPool and GatewayConnection."""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.gateway.connection_pool import GatewayConnection, GatewayConnectionPool


class TestGatewayConnection:

    @pytest.fixture
    def mock_management_api(self):
        client = MagicMock()
        client.send_message = MagicMock(return_value=True)
        return client

    @pytest.fixture
    def connection(self, mock_management_api):
        return GatewayConnection(
            user_id="test-user", ip="10.0.0.1", token="test-token",
            management_api=mock_management_api,
        )

    @pytest.mark.asyncio
    async def test_send_rpc_formats_request(self, connection):
        """send_rpc should send a properly formatted OpenClaw req message."""
        connection._ws = AsyncMock()
        await connection.send_rpc("req-123", "health", {})
        connection._ws.send.assert_called_once()
        sent = json.loads(connection._ws.send.call_args[0][0])
        assert sent == {"type": "req", "id": "req-123", "method": "health", "params": {}}

    @pytest.mark.asyncio
    async def test_handle_res_resolves_future(self, connection):
        """_handle_message with type=res should resolve the matching Future."""
        future = asyncio.get_event_loop().create_future()
        connection._pending_rpcs["req-456"] = future
        connection._handle_message({"type": "res", "id": "req-456", "ok": True, "payload": {"uptime": 3600}})
        result = await asyncio.wait_for(future, timeout=1)
        assert result == {"uptime": 3600}

    @pytest.mark.asyncio
    async def test_handle_res_error_rejects_future(self, connection):
        """_handle_message with type=res ok=false should reject the Future."""
        future = asyncio.get_event_loop().create_future()
        connection._pending_rpcs["req-789"] = future
        connection._handle_message({"type": "res", "id": "req-789", "ok": False, "error": {"message": "not found"}})
        with pytest.raises(RuntimeError, match="not found"):
            await asyncio.wait_for(future, timeout=1)

    def test_handle_event_forwards_to_frontend(self, connection, mock_management_api):
        """_handle_message with type=event should forward to all frontend connections."""
        connection._frontend_connections.add("conn-abc")
        connection._frontend_connections.add("conn-def")
        connection._handle_message({"type": "event", "event": "health", "payload": {"status": "ok"}})
        assert mock_management_api.send_message.call_count == 2

    def test_add_remove_frontend_connection(self, connection):
        """Should track frontend connection IDs."""
        connection.add_frontend_connection("conn-1")
        connection.add_frontend_connection("conn-2")
        assert len(connection._frontend_connections) == 2
        connection.remove_frontend_connection("conn-1")
        assert len(connection._frontend_connections) == 1

    @pytest.mark.asyncio
    async def test_close_cancels_reader(self, connection):
        """close() should cancel the reader task and close the WS."""
        connection._ws = AsyncMock()
        connection._reader_task = asyncio.create_task(asyncio.sleep(100))
        await connection.close()
        assert connection._reader_task.cancelled()
        connection._ws.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_wait_for_response_times_out(self, connection):
        """wait_for_response should raise TimeoutError after timeout."""
        connection._pending_rpcs["req-timeout"] = asyncio.get_event_loop().create_future()
        with pytest.raises(asyncio.TimeoutError):
            await connection.wait_for_response("req-timeout", timeout=0.1)
        assert "req-timeout" not in connection._pending_rpcs


class TestGatewayConnectionPool:

    @pytest.fixture
    def pool(self):
        return GatewayConnectionPool(management_api=MagicMock())

    def test_add_remove_frontend_connection(self, pool):
        """Should track user's frontend connections."""
        pool.add_frontend_connection("user-1", "conn-abc")
        assert "conn-abc" in pool._frontend_connections["user-1"]
        pool.remove_frontend_connection("user-1", "conn-abc")
        assert len(pool._frontend_connections.get("user-1", set())) == 0

    @pytest.mark.asyncio
    async def test_send_rpc_creates_connection(self, pool):
        """send_rpc should create a GatewayConnection if none exists."""
        mock_conn = AsyncMock(spec=GatewayConnection)
        mock_conn.is_connected = True
        mock_conn.wait_for_response = AsyncMock(return_value={"status": "ok"})
        mock_conn._frontend_connections = set()
        with patch.object(pool, "_create_connection", return_value=mock_conn):
            result = await pool.send_rpc("user-1", "req-1", "health", {}, "10.0.0.1", "tok")
            assert result == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_send_rpc_reuses_existing(self, pool):
        """send_rpc should reuse an existing connected GatewayConnection."""
        mock_conn = AsyncMock(spec=GatewayConnection)
        mock_conn.is_connected = True
        mock_conn.wait_for_response = AsyncMock(return_value={"data": 1})
        mock_conn._frontend_connections = set()
        pool._connections["user-1"] = mock_conn
        result = await pool.send_rpc("user-1", "req-2", "agents.list", {}, "10.0.0.1", "tok")
        assert result == {"data": 1}
        mock_conn.send_rpc.assert_called_once_with("req-2", "agents.list", {})

    @pytest.mark.asyncio
    async def test_close_all(self, pool):
        """close_all should close every connection."""
        mock_conn = AsyncMock(spec=GatewayConnection)
        pool._connections["user-1"] = mock_conn
        await pool.close_all()
        mock_conn.close.assert_called_once()
        assert len(pool._connections) == 0
```

**Commit:**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend
git add core/gateway/connection_pool.py tests/unit/core/test_connection_pool.py
git commit -m "feat: add GatewayConnection + GatewayConnectionPool with tests"
```

---

## Task 2: Backend — Export Pool Singleton

**Files:**
- Modify: `backend/core/containers/__init__.py`

**Changes:**

After line 15 (`from core.containers.http_client import ...`), add:

```python
from core.gateway.connection_pool import GatewayConnectionPool
```

After `_workspace` declaration (line 20), add:

```python
_gateway_pool: Optional[GatewayConnectionPool] = None
```

After `get_workspace()` function (after line 38), add:

```python
def get_gateway_pool() -> GatewayConnectionPool:
    """Get the gateway connection pool singleton."""
    global _gateway_pool
    if _gateway_pool is None:
        from core.services.management_api_client import ManagementApiClient
        _gateway_pool = GatewayConnectionPool(
            management_api=ManagementApiClient(),
        )
    return _gateway_pool
```

Add `"GatewayConnectionPool"` and `"get_gateway_pool"` to the `__all__` list.

**Commit:**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend
git add core/containers/__init__.py
git commit -m "feat: export GatewayConnectionPool singleton"
```

---

## Task 3: Backend — Add `req` Message Type to websocket_chat.py

**Files:**
- Modify: `backend/routers/websocket_chat.py`
- Modify: `backend/tests/unit/routers/test_websocket_chat.py`

**Step 1: Add `req` handler to websocket_chat.py**

Add import at top (after line 18):

```python
from core.containers import get_gateway_pool
```

In `ws_connect()`, add pool registration before `return Response(status_code=200)` (before line 85):

```python
    try:
        pool = get_gateway_pool()
        pool.add_frontend_connection(x_user_id, x_connection_id)
    except Exception as e:
        logger.warning("Failed to register frontend connection with pool: %s", e)
```

In `ws_disconnect()`, add pool unregistration after the town viewer cleanup block (after line 109), before the connection service delete:

```python
    try:
        connection_service = get_connection_service()
        connection = connection_service.get_connection(x_connection_id)
        if connection:
            pool = get_gateway_pool()
            pool.remove_frontend_connection(connection["user_id"], x_connection_id)
    except Exception as e:
        logger.warning("Failed to unregister frontend connection from pool: %s", e)
```

In `ws_message()`, add `req` handler before the `if msg_type == "agent_chat":` block (before line 170):

```python
    if msg_type == "req":
        req_id = body.get("id")
        method = body.get("method")
        params = body.get("params", {})

        if not req_id or not method:
            management_api = get_management_api_client()
            management_api.send_message(
                x_connection_id,
                {
                    "type": "res",
                    "id": req_id,
                    "ok": False,
                    "error": {"message": "Missing id or method"},
                },
            )
            return Response(status_code=200)

        background_tasks.add_task(
            _process_rpc_background,
            connection_id=x_connection_id,
            user_id=user_id,
            req_id=req_id,
            method=method,
            params=params,
        )
        return Response(status_code=200)
```

Add `_process_rpc_background` function after `ws_message`:

```python
async def _process_rpc_background(
    connection_id: str,
    user_id: str,
    req_id: str,
    method: str,
    params: dict,
) -> None:
    """Process an OpenClaw RPC request via the gateway connection pool."""
    management_api = get_management_api_client()

    try:
        ecs_manager = get_ecs_manager()
        session_factory = get_session_factory()
        async with session_factory() as db:
            container, ip = await ecs_manager.resolve_running_container(user_id, db)

        if not container:
            management_api.send_message(connection_id, {
                "type": "res", "id": req_id, "ok": False,
                "error": {"message": "No container provisioned."},
            })
            return

        if not ip:
            management_api.send_message(connection_id, {
                "type": "res", "id": req_id, "ok": False,
                "error": {"message": "Container is starting up. Try again in a moment."},
            })
            return

        pool = get_gateway_pool()
        result = await pool.send_rpc(
            user_id=user_id,
            req_id=req_id,
            method=method,
            params=params,
            ip=ip,
            token=container.gateway_token,
        )
        management_api.send_message(connection_id, {
            "type": "res", "id": req_id, "ok": True, "payload": result,
        })

    except Exception as e:
        logger.error("RPC %s failed for user %s: %s", method, user_id, e)
        try:
            management_api.send_message(connection_id, {
                "type": "res", "id": req_id, "ok": False,
                "error": {"message": str(e)},
            })
        except Exception:
            pass
```

**Step 2: Add tests for `req` message type**

Append to `backend/tests/unit/routers/test_websocket_chat.py`:

```python
class TestReqMessageRouting:
    """Tests for type=req RPC proxy messages."""

    @pytest.mark.asyncio
    async def test_req_message_accepted(
        self, test_app, mock_connection_service, mock_management_api, mock_session_factory
    ):
        """Valid req message should be accepted and return 200."""
        mock_connection_service.get_connection.return_value = {
            "user_id": "test-user",
            "org_id": None,
        }

        async with AsyncClient(
            transport=ASGITransport(app=test_app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/ws/message",
                headers={"x-connection-id": "conn-123"},
                json={
                    "type": "req",
                    "id": "req-uuid-1",
                    "method": "health",
                    "params": {},
                },
            )

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_req_missing_id_sends_error(
        self, test_app, mock_connection_service, mock_management_api
    ):
        """req without id should send error res back."""
        mock_connection_service.get_connection.return_value = {
            "user_id": "test-user",
            "org_id": None,
        }

        async with AsyncClient(
            transport=ASGITransport(app=test_app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/ws/message",
                headers={"x-connection-id": "conn-123"},
                json={"type": "req", "method": "health"},
            )

        assert response.status_code == 200
        mock_management_api.send_message.assert_called_once()
        sent_msg = mock_management_api.send_message.call_args[0][1]
        assert sent_msg["type"] == "res"
        assert sent_msg["ok"] is False

    @pytest.mark.asyncio
    async def test_req_missing_method_sends_error(
        self, test_app, mock_connection_service, mock_management_api
    ):
        """req without method should send error res back."""
        mock_connection_service.get_connection.return_value = {
            "user_id": "test-user",
            "org_id": None,
        }

        async with AsyncClient(
            transport=ASGITransport(app=test_app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/ws/message",
                headers={"x-connection-id": "conn-123"},
                json={"type": "req", "id": "req-uuid-2"},
            )

        assert response.status_code == 200
        sent_msg = mock_management_api.send_message.call_args[0][1]
        assert sent_msg["type"] == "res"
        assert sent_msg["id"] == "req-uuid-2"
        assert sent_msg["ok"] is False
```

**Commit:**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend
git add routers/websocket_chat.py tests/unit/routers/test_websocket_chat.py
git commit -m "feat: add req message type for WebSocket RPC proxy"
```

---

## Task 4: Backend — Deprecate POST /container/rpc

**Files:**
- Modify: `backend/routers/container_rpc.py`

Update the `@router.post("/rpc", ...)` decorator (line 153):

```python
    summary="[Deprecated] Proxy RPC call to user's OpenClaw container",
    description=(
        "DEPRECATED: Use WebSocket req/res protocol instead. "
        "This HTTP fallback will be removed in a future release. "
        "Forwards a JSON-RPC call to the user's dedicated OpenClaw container."
    ),
    deprecated=True,
```

**Commit:**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend
git add routers/container_rpc.py
git commit -m "chore: mark POST /container/rpc as deprecated"
```

---

## Task 5: Frontend — GatewayProvider Context

**Files:**
- Create: `frontend/src/hooks/useGateway.tsx`

```typescript
// frontend/src/hooks/useGateway.tsx
"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useAuth } from "@clerk/nextjs";

// =============================================================================
// Constants
// =============================================================================

const MAX_RECONNECT_ATTEMPTS = 5;
const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 16000];
const PING_INTERVAL_MS = 30000;
const CONNECTION_TIMEOUT_MS = 10000;
const RPC_TIMEOUT_MS = 30000;

function getWebSocketUrl(): string {
  if (process.env.NEXT_PUBLIC_WS_URL) {
    return process.env.NEXT_PUBLIC_WS_URL;
  }
  const apiUrl =
    process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";
  return apiUrl
    .replace(/^https:\/\//, "wss://")
    .replace(/^http:\/\//, "ws://")
    .replace("api-", "ws-")
    .replace(/\/api\/v1$/, "");
}

// =============================================================================
// Types
// =============================================================================

/** Chat message types received from backend */
export type ChatIncomingMessage =
  | { type: "chunk"; content: string }
  | { type: "done" }
  | { type: "error"; message: string }
  | { type: "heartbeat" };

/** Gateway event forwarded from OpenClaw */
export interface GatewayEvent {
  type: "event";
  event: string;
  payload: unknown;
}

interface PendingRpc {
  resolve: (value: unknown) => void;
  reject: (reason: Error) => void;
  timeout: ReturnType<typeof setTimeout>;
}

interface GatewayContextValue {
  isConnected: boolean;
  error: string | null;
  sendReq: (method: string, params?: Record<string, unknown>) => Promise<unknown>;
  sendChat: (agentName: string, message: string) => void;
  onEvent: (handler: (event: string, data: unknown) => void) => () => void;
  onChatMessage: (handler: (msg: ChatIncomingMessage) => void) => () => void;
}

const GatewayContext = createContext<GatewayContextValue | null>(null);

// =============================================================================
// Provider
// =============================================================================

export function GatewayProvider({ children }: { children: ReactNode }) {
  const { getToken } = useAuth();
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptRef = useRef(0);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pingIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pendingRpcsRef = useRef<Map<string, PendingRpc>>(new Map());
  const eventHandlersRef = useRef<Set<(event: string, data: unknown) => void>>(new Set());
  const chatHandlersRef = useRef<Set<(msg: ChatIncomingMessage) => void>>(new Set());

  // ---- Cleanup helpers ----

  const clearPingInterval = useCallback(() => {
    if (pingIntervalRef.current) {
      clearInterval(pingIntervalRef.current);
      pingIntervalRef.current = null;
    }
  }, []);

  const clearReconnectTimeout = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
  }, []);

  // ---- Message router ----

  const handleMessage = useCallback((event: MessageEvent) => {
    if (!event.data || typeof event.data !== "string") return;
    let data: Record<string, unknown>;
    try {
      data = JSON.parse(event.data);
    } catch {
      return;
    }

    const msgType = data.type as string;

    // OpenClaw res — resolve pending RPC
    if (msgType === "res" && typeof data.id === "string") {
      const pending = pendingRpcsRef.current.get(data.id);
      if (pending) {
        clearTimeout(pending.timeout);
        pendingRpcsRef.current.delete(data.id);
        if (data.ok) {
          pending.resolve(data.payload);
        } else {
          const errMsg =
            (data.error as Record<string, unknown>)?.message || "RPC call failed";
          pending.reject(new Error(String(errMsg)));
        }
      }
      return;
    }

    // OpenClaw event — dispatch to subscribers
    if (msgType === "event") {
      const eventName = data.event as string;
      for (const handler of eventHandlersRef.current) {
        try {
          handler(eventName, data.payload);
        } catch {
          // subscriber error, ignore
        }
      }
      return;
    }

    // Chat messages — dispatch to subscribers
    if (
      msgType === "chunk" ||
      msgType === "done" ||
      msgType === "error" ||
      msgType === "heartbeat"
    ) {
      const chatMsg = data as unknown as ChatIncomingMessage;
      for (const handler of chatHandlersRef.current) {
        try {
          handler(chatMsg);
        } catch {
          // subscriber error, ignore
        }
      }
      return;
    }

    // pong — nothing to do
  }, []);

  // ---- Connect ----

  const connect = useCallback(async () => {
    if (
      wsRef.current?.readyState === WebSocket.OPEN ||
      wsRef.current?.readyState === WebSocket.CONNECTING
    ) {
      return;
    }

    try {
      const token = await getToken();
      if (!token) throw new Error("Not authenticated");

      const wsUrl = getWebSocketUrl();
      const ws = new WebSocket(`${wsUrl}?token=${token}`);

      ws.onopen = () => {
        reconnectAttemptRef.current = 0;
        setIsConnected(true);
        setError(null);

        clearPingInterval();
        pingIntervalRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: "ping" }));
          }
        }, PING_INTERVAL_MS);
      };

      ws.onclose = (event) => {
        wsRef.current = null;
        setIsConnected(false);
        clearPingInterval();

        // Reject all pending RPCs
        for (const [id, pending] of pendingRpcsRef.current) {
          clearTimeout(pending.timeout);
          pending.reject(new Error("WebSocket closed"));
        }
        pendingRpcsRef.current.clear();

        if (event.code === 1000 || event.code === 4001) {
          if (event.code === 4001) {
            setError("Authentication failed. Please refresh the page.");
          }
          return;
        }

        if (reconnectAttemptRef.current < MAX_RECONNECT_ATTEMPTS) {
          const delay =
            RECONNECT_DELAYS[reconnectAttemptRef.current] || 16000;
          reconnectAttemptRef.current++;
          reconnectTimeoutRef.current = setTimeout(() => connect(), delay);
        } else {
          setError("Connection lost. Please refresh the page.");
        }
      };

      ws.onerror = () => {};
      ws.onmessage = handleMessage;
      wsRef.current = ws;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to connect");
    }
  }, [getToken, handleMessage, clearPingInterval]);

  // ---- Auto-connect on mount ----

  useEffect(() => {
    connect();
    return () => {
      clearReconnectTimeout();
      clearPingInterval();
      if (wsRef.current) {
        wsRef.current.close(1000, "Provider unmounted");
        wsRef.current = null;
      }
    };
  }, [connect, clearReconnectTimeout, clearPingInterval]);

  // ---- sendReq ----

  const sendReq = useCallback(
    async (method: string, params?: Record<string, unknown>): Promise<unknown> => {
      // Ensure connected
      if (wsRef.current?.readyState !== WebSocket.OPEN) {
        await connect();
        await new Promise<void>((resolve, reject) => {
          const timeout = setTimeout(
            () => reject(new Error("Connection timeout")),
            CONNECTION_TIMEOUT_MS,
          );
          const check = setInterval(() => {
            if (wsRef.current?.readyState === WebSocket.OPEN) {
              clearTimeout(timeout);
              clearInterval(check);
              resolve();
            }
          }, 100);
        });
      }

      const id = crypto.randomUUID();

      return new Promise((resolve, reject) => {
        const timeout = setTimeout(() => {
          pendingRpcsRef.current.delete(id);
          reject(new Error(`RPC timeout: ${method}`));
        }, RPC_TIMEOUT_MS);

        pendingRpcsRef.current.set(id, { resolve, reject, timeout });

        wsRef.current!.send(
          JSON.stringify({ type: "req", id, method, params: params || {} }),
        );
      });
    },
    [connect],
  );

  // ---- sendChat ----

  const sendChat = useCallback(
    (agentName: string, message: string) => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(
          JSON.stringify({
            type: "agent_chat",
            agent_name: agentName,
            message,
          }),
        );
      }
    },
    [],
  );

  // ---- Subscription helpers ----

  const onEvent = useCallback(
    (handler: (event: string, data: unknown) => void) => {
      eventHandlersRef.current.add(handler);
      return () => {
        eventHandlersRef.current.delete(handler);
      };
    },
    [],
  );

  const onChatMessage = useCallback(
    (handler: (msg: ChatIncomingMessage) => void) => {
      chatHandlersRef.current.add(handler);
      return () => {
        chatHandlersRef.current.delete(handler);
      };
    },
    [],
  );

  return (
    <GatewayContext.Provider
      value={{ isConnected, error, sendReq, sendChat, onEvent, onChatMessage }}
    >
      {children}
    </GatewayContext.Provider>
  );
}

// =============================================================================
// Hook
// =============================================================================

export function useGateway(): GatewayContextValue {
  const ctx = useContext(GatewayContext);
  if (!ctx) {
    throw new Error("useGateway must be used within a GatewayProvider");
  }
  return ctx;
}
```

**Commit:**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/freebird/frontend
git add src/hooks/useGateway.tsx
git commit -m "feat: add GatewayProvider — shared WebSocket context for RPC and chat"
```

---

## Task 6: Frontend — useGatewayRpc Hook

**Files:**
- Create: `frontend/src/hooks/useGatewayRpc.ts`

```typescript
// frontend/src/hooks/useGatewayRpc.ts
"use client";

import { useCallback, useEffect } from "react";
import useSWR, { SWRConfiguration } from "swr";
import { useGateway } from "@/hooks/useGateway";

interface RpcResult<T = unknown> {
  data: T | undefined;
  error: Error | undefined;
  isLoading: boolean;
  mutate: () => void;
}

/**
 * Hook for read-only RPC calls via the gateway WebSocket (auto-fetched via SWR).
 *
 * Drop-in replacement for useContainerRpc. Same API, same return type.
 *
 * Usage:
 *   const { data, isLoading } = useGatewayRpc<HealthData>("health");
 *   const { data } = useGatewayRpc<AgentList>("agents.list");
 */
export function useGatewayRpc<T = unknown>(
  method: string | null,
  params?: Record<string, unknown>,
  config?: SWRConfiguration,
): RpcResult<T> {
  const { sendReq, onEvent } = useGateway();

  const fetcher = useCallback(
    async (key: string) => {
      const [, m, paramStr] = key.split("|");
      const parsedParams = paramStr ? JSON.parse(paramStr) : undefined;
      try {
        return (await sendReq(m, parsedParams)) as T;
      } catch (err) {
        // Match old behavior: 404-equivalent returns undefined
        if (err instanceof Error && err.message.includes("No container")) {
          return undefined;
        }
        throw err;
      }
    },
    [sendReq],
  );

  const swrKey = method
    ? `rpc|${method}|${params ? JSON.stringify(params) : ""}`
    : null;

  const { data, error, isLoading, mutate } = useSWR<T | undefined>(
    swrKey as string | null,
    fetcher as (key: string) => Promise<T | undefined>,
    {
      revalidateOnFocus: false,
      dedupingInterval: 10000,
      ...config,
    },
  );

  // Auto-revalidate when gateway pushes a matching event
  useEffect(() => {
    if (!method) return;
    return onEvent((event) => {
      if (method === event || method.startsWith(event + ".")) {
        mutate();
      }
    });
  }, [method, onEvent, mutate]);

  return {
    data,
    error: error as Error | undefined,
    isLoading,
    mutate: () => {
      mutate();
    },
  };
}

/**
 * Hook for write RPC calls via the gateway WebSocket (imperative, not auto-fetched).
 *
 * Drop-in replacement for useContainerRpcMutation.
 *
 * Usage:
 *   const callRpc = useGatewayRpcMutation();
 *   await callRpc("config.set", { key: "value" });
 */
export function useGatewayRpcMutation() {
  const { sendReq } = useGateway();

  return useCallback(
    async <T = unknown>(
      method: string,
      params?: Record<string, unknown>,
    ): Promise<T> => {
      return (await sendReq(method, params)) as T;
    },
    [sendReq],
  );
}
```

**Commit:**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/freebird/frontend
git add src/hooks/useGatewayRpc.ts
git commit -m "feat: add useGatewayRpc — WebSocket-based drop-in for useContainerRpc"
```

---

## Task 7: Frontend — Refactor useAgentChat

**Files:**
- Rewrite: `frontend/src/hooks/useAgentChat.ts`

Remove all WebSocket management. Use `sendChat` and `onChatMessage` from GatewayProvider.

```typescript
// frontend/src/hooks/useAgentChat.ts
/**
 * Agent chat hook that uses the shared GatewayProvider WebSocket.
 *
 * Message protocol (unchanged):
 * - Send: { type: "agent_chat", agent_name: string, message: string }
 * - Receive: { type: "chunk", content: string }
 * - Receive: { type: "done" }
 * - Receive: { type: "error", message: string }
 * - Receive: { type: "heartbeat" }
 */

"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import { useGateway, type ChatIncomingMessage } from "@/hooks/useGateway";

// =============================================================================
// Types
// =============================================================================

export interface AgentMessage {
  role: "user" | "assistant";
  content: string;
}

export interface UseAgentChatReturn {
  messages: AgentMessage[];
  isStreaming: boolean;
  error: string | null;
  sendMessage: (message: string) => Promise<void>;
  clearMessages: () => void;
  isConnected: boolean;
}

interface InternalMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
}

// =============================================================================
// Hook
// =============================================================================

export function useAgentChat(agentName: string | null): UseAgentChatReturn {
  const { isConnected, sendChat, onChatMessage } = useGateway();

  const [messages, setMessages] = useState<InternalMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const currentAssistantIdRef = useRef<string | null>(null);
  const streamContentRef = useRef<string>("");
  const agentNameRef = useRef(agentName);
  agentNameRef.current = agentName;

  // ---- Chat message handler ----

  useEffect(() => {
    return onChatMessage((msg: ChatIncomingMessage) => {
      // Only process if we're currently streaming
      if (!currentAssistantIdRef.current) return;

      if (msg.type === "chunk") {
        streamContentRef.current += msg.content;
        const updatedContent = streamContentRef.current;
        setMessages((prev) =>
          prev.map((m) =>
            m.id === currentAssistantIdRef.current
              ? { ...m, content: updatedContent }
              : m,
          ),
        );
        return;
      }

      if (msg.type === "done") {
        setIsStreaming(false);
        currentAssistantIdRef.current = null;
        streamContentRef.current = "";
        return;
      }

      if (msg.type === "error") {
        if (currentAssistantIdRef.current) {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === currentAssistantIdRef.current
                ? { ...m, content: `Error: ${msg.message}` }
                : m,
            ),
          );
        }
        setError(msg.message);
        setIsStreaming(false);
        currentAssistantIdRef.current = null;
        streamContentRef.current = "";
        return;
      }

      if (msg.type === "heartbeat") {
        if (!streamContentRef.current && currentAssistantIdRef.current) {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === currentAssistantIdRef.current
                ? { ...m, content: "Agent is working..." }
                : m,
            ),
          );
        }
      }
    });
  }, [onChatMessage]);

  // ---- Send message ----

  const sendMessage = useCallback(
    async (message: string): Promise<void> => {
      if (!agentNameRef.current) {
        throw new Error("No agent selected");
      }

      setError(null);

      const userMsgId = `user-${Date.now()}`;
      const assistantMsgId = `assistant-${Date.now()}`;

      currentAssistantIdRef.current = assistantMsgId;
      streamContentRef.current = "";

      setMessages((prev) => [
        ...prev,
        { id: userMsgId, role: "user", content: message },
        { id: assistantMsgId, role: "assistant", content: "" },
      ]);
      setIsStreaming(true);

      try {
        sendChat(agentNameRef.current, message);
      } catch (err) {
        const errorMessage =
          err instanceof Error ? err.message : "Failed to send message";
        setError(errorMessage);
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMsgId
              ? { ...m, content: `Error: ${errorMessage}` }
              : m,
          ),
        );
        setIsStreaming(false);
        currentAssistantIdRef.current = null;
        streamContentRef.current = "";
      }
    },
    [sendChat],
  );

  // ---- Clear messages ----

  const clearMessages = useCallback(() => {
    setMessages([]);
    setError(null);
    setIsStreaming(false);
    currentAssistantIdRef.current = null;
    streamContentRef.current = "";
  }, []);

  // ---- Clear on agent change ----

  const prevAgentNameRef = useRef<string | null | undefined>(undefined);

  useEffect(() => {
    if (prevAgentNameRef.current === undefined) {
      prevAgentNameRef.current = agentName;
      return;
    }
    if (prevAgentNameRef.current !== agentName) {
      clearMessages();
      prevAgentNameRef.current = agentName;
    }
  }, [agentName, clearMessages]);

  // ---- External interface ----

  const externalMessages: AgentMessage[] = messages.map(({ role, content }) => ({
    role,
    content,
  }));

  return {
    messages: externalMessages,
    isStreaming,
    error,
    sendMessage,
    clearMessages,
    isConnected,
  };
}
```

**Commit:**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/freebird/frontend
git add src/hooks/useAgentChat.ts
git commit -m "refactor: useAgentChat now uses shared GatewayProvider WebSocket"
```

---

## Task 8: Frontend — Wrap Chat Page + Swap All Imports + Cleanup

**Files:**
- Modify: `frontend/src/app/chat/page.tsx` — add GatewayProvider wrapper
- Modify: 13 component files — swap `useContainerRpc` → `useGatewayRpc`
- Delete: `frontend/src/hooks/useContainerRpc.ts`
- Modify: `frontend/src/hooks/index.ts` — update exports

**Step 1: Wrap chat page with GatewayProvider**

In `frontend/src/app/chat/page.tsx`, add import:

```typescript
import { GatewayProvider } from "@/hooks/useGateway";
```

Wrap the return JSX with `<GatewayProvider>...</GatewayProvider>`.

**Step 2: In all 13 files, swap imports**

For each file, replace:
- `import { useContainerRpc } from "@/hooks/useContainerRpc"` → `import { useGatewayRpc } from "@/hooks/useGatewayRpc"`
- `import { useContainerRpc, useContainerRpcMutation } from "@/hooks/useContainerRpc"` → `import { useGatewayRpc, useGatewayRpcMutation } from "@/hooks/useGatewayRpc"`

And rename all call sites:
- `useContainerRpc(` → `useGatewayRpc(`
- `useContainerRpcMutation(` → `useGatewayRpcMutation(`

Files to change:
1. `src/components/chat/ContainerGate.tsx`
2. `src/components/control/panels/OverviewPanel.tsx`
3. `src/components/control/panels/ChannelsPanel.tsx`
4. `src/components/control/panels/AgentsPanel.tsx`
5. `src/components/control/panels/ConfigPanel.tsx`
6. `src/components/control/panels/SessionsPanel.tsx`
7. `src/components/control/panels/CronPanel.tsx`
8. `src/components/control/panels/LogsPanel.tsx`
9. `src/components/control/panels/DebugPanel.tsx`
10. `src/components/control/panels/InstancesPanel.tsx`
11. `src/components/control/panels/NodesPanel.tsx`
12. `src/components/control/panels/SkillsPanel.tsx`
13. `src/components/control/panels/UsagePanel.tsx`

**Step 3: Delete useContainerRpc.ts**

```bash
rm frontend/src/hooks/useContainerRpc.ts
```

**Step 4: Update index.ts**

Replace `frontend/src/hooks/index.ts` with:

```typescript
/**
 * React hooks for the Isol8 agent platform.
 */

export { useAgents } from './useAgents';
export { useAgentChat, type UseAgentChatReturn, type AgentMessage } from './useAgentChat';
export { useBilling } from './useBilling';
export { useContainerStatus } from './useContainerStatus';
export { GatewayProvider, useGateway, type ChatIncomingMessage, type GatewayEvent } from './useGateway';
export { useGatewayRpc, useGatewayRpcMutation } from './useGatewayRpc';
```

**Commit:**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/freebird/frontend
git add -A src/
git commit -m "refactor: swap all panels to useGatewayRpc, delete useContainerRpc"
```

---

## Task 9: Run All Tests + Verify

Run tests only for the code we changed. Do NOT run the full test suite.

**Step 1: Backend — connection pool tests (new)**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend && python -m pytest tests/unit/core/test_connection_pool.py -v`

Expected: All 11 tests PASS

**Step 2: Backend — websocket chat route tests (modified)**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend && python -m pytest tests/unit/routers/test_websocket_chat.py tests/unit/routers/test_websocket_agent_chat.py -v`

Expected: All existing + 3 new tests PASS. If any fail due to the new `get_gateway_pool` import, add a mock for it in the test fixtures.

**Step 3: Frontend — TypeScript compilation**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/freebird/frontend && npx tsc --noEmit --pretty 2>&1 | head -30`

Expected: No errors

**Step 4: Frontend — build**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/freebird/frontend && npm run build`

Expected: Build succeeds

**Step 5: Verify no stale imports**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/freebird/frontend && grep -r "useContainerRpc" src/ --include="*.ts" --include="*.tsx"`

Expected: No matches

---

## Summary

| Task | Side | What |
|------|------|------|
| 1 | Backend | GatewayConnection + GatewayConnectionPool + tests |
| 2 | Backend | Export pool singleton from containers module |
| 3 | Backend | Add `req` message type to websocket_chat.py + tests |
| 4 | Backend | Deprecate HTTP RPC endpoint |
| 5 | Frontend | GatewayProvider context (shared WS manager) |
| 6 | Frontend | useGatewayRpc hook (drop-in replacement) |
| 7 | Frontend | Refactor useAgentChat to use GatewayProvider |
| 8 | Frontend | Wrap page + swap all imports + delete old hook |
| 9 | Both | Run tests + verify build |
