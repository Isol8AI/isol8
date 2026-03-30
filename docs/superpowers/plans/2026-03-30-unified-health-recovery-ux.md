# Unified Health & Recovery UX — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace scattered container/gateway status indicators with a unified 5-state health model, persistent sidebar indicator, and single "Fix it" button that takes the right recovery action.

**Architecture:** Backend gets a new `POST /container/recover` endpoint that inspects container + gateway state and dispatches the correct recovery action (gateway restart or full re-provision). Frontend gets a `useSystemHealth` hook merging REST poll + WS health RPC + WS push events into a single state, rendered as a persistent dot in the sidebar. The auto-hiding `ConnectionStatusBar` is removed.

**Tech Stack:** FastAPI (backend), React 19 + SWR (frontend), DynamoDB (container state), WebSocket Management API (push events)

**Spec:** `docs/superpowers/specs/2026-03-30-unified-health-recovery-ux-design.md`

---

## File Structure

### New files
| File | Responsibility |
|------|---------------|
| `apps/backend/routers/container_recover.py` | `POST /recover` endpoint — state inspection, locking, recovery dispatch |
| `apps/backend/tests/unit/routers/test_container_recover.py` | Tests for recover endpoint |
| `apps/frontend/src/hooks/useSystemHealth.ts` | Unified health state hook — merges 3 signal sources into `{state, reason}` |
| `apps/frontend/src/components/chat/HealthIndicator.tsx` | Sidebar health dot + label + "Fix it" button |

### Modified files
| File | Change |
|------|--------|
| `apps/backend/core/repositories/container_repo.py` | Add `update_error()` helper |
| `apps/backend/core/gateway/connection_pool.py` | Emit `status_change` push events on gateway connect/disconnect |
| `apps/backend/main.py` | Register `container_recover` router |
| `apps/backend/routers/container.py` | Return `last_error`/`last_error_at` in status response |
| `apps/frontend/src/components/chat/Sidebar.tsx` | Render `HealthIndicator` at top |
| `apps/frontend/src/components/chat/AgentChatWindow.tsx` | Remove `ConnectionStatusBar` import/render |
| `apps/frontend/src/components/chat/ProvisioningStepper.tsx` | Add `trigger` prop for recovery flow |
| `apps/frontend/src/components/control/panels/OverviewPanel.tsx` | Remove 4 action buttons, add health summary |
| `apps/frontend/src/hooks/useContainerStatus.ts` | Add `last_error`/`last_error_at` to `ContainerStatus` type |

### Removed files
| File | Reason |
|------|--------|
| `apps/frontend/src/components/chat/ConnectionStatusBar.tsx` | Replaced by HealthIndicator |

---

## Task 1: Add `last_error` fields to container repo and status endpoint

**Files:**
- Modify: `apps/backend/core/repositories/container_repo.py`
- Modify: `apps/backend/routers/container.py`
- Modify: `apps/backend/tests/unit/routers/test_container_status.py`

- [ ] **Step 1: Write test for `last_error` in status response**

In `apps/backend/tests/unit/routers/test_container_status.py`, add a test to `TestContainerStatus`:

```python
@pytest.mark.asyncio
@patch("routers.container.get_ecs_manager")
async def test_returns_last_error_fields(self, mock_get_ecs, async_client):
    """Should include last_error and last_error_at when present."""
    mock_ecs = AsyncMock()
    mock_get_ecs.return_value = mock_ecs
    mock_ecs.resolve_running_container = AsyncMock(
        return_value=(
            {
                "owner_id": "user_test_123",
                "service_name": "openclaw-abc123",
                "gateway_token": "secret-token-value",
                "status": "error",
                "substatus": None,
                "task_arn": "arn:aws:ecs:us-east-1:123456789:task/test-task",
                "access_point_id": "fsap-test123",
                "created_at": "2026-01-15T12:00:00+00:00",
                "updated_at": "2026-01-15T14:00:00+00:00",
                "last_error": "OutOfMemoryError",
                "last_error_at": "2026-01-15T13:59:00+00:00",
            },
            "10.0.1.5",
        )
    )

    response = await async_client.get("/api/v1/container/status")
    data = response.json()
    assert data["last_error"] == "OutOfMemoryError"
    assert data["last_error_at"] == "2026-01-15T13:59:00+00:00"


@pytest.mark.asyncio
@patch("routers.container.get_ecs_manager")
async def test_returns_null_last_error_when_absent(self, mock_get_ecs, async_client):
    """Should return null for last_error fields when not set."""
    mock_ecs = AsyncMock()
    mock_get_ecs.return_value = mock_ecs
    mock_ecs.resolve_running_container = AsyncMock(
        return_value=(
            {
                "owner_id": "user_test_123",
                "service_name": "openclaw-abc123",
                "gateway_token": "secret-token-value",
                "status": "running",
                "substatus": None,
                "task_arn": "arn:aws:ecs:us-east-1:123456789:task/test-task",
                "access_point_id": "fsap-test123",
                "created_at": "2026-01-15T12:00:00+00:00",
                "updated_at": "2026-01-15T14:00:00+00:00",
            },
            "10.0.1.5",
        )
    )

    response = await async_client.get("/api/v1/container/status")
    data = response.json()
    assert data["last_error"] is None
    assert data["last_error_at"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && uv run pytest tests/unit/routers/test_container_status.py -v`

Expected: FAIL — `last_error` and `last_error_at` not in response.

- [ ] **Step 3: Add `update_error` helper to container_repo**

In `apps/backend/core/repositories/container_repo.py`, add after the `update_fields` function (after line 76):

```python
async def update_error(owner_id: str, error: str) -> dict | None:
    """Record the last error for a container."""
    from core.dynamodb import utc_now_iso

    return await update_fields(owner_id, {
        "last_error": error,
        "last_error_at": utc_now_iso(),
    })
```

- [ ] **Step 4: Add `last_error` fields to status response**

In `apps/backend/routers/container.py`, modify the return dict in `container_status` (lines 73-80) to include:

```python
    return {
        "service_name": container.get("service_name"),
        "status": container.get("status"),
        "substatus": container.get("substatus"),
        "created_at": container.get("created_at"),
        "updated_at": container.get("updated_at"),
        "region": settings.AWS_REGION,
        "last_error": container.get("last_error"),
        "last_error_at": container.get("last_error_at"),
    }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd apps/backend && uv run pytest tests/unit/routers/test_container_status.py -v`

Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/core/repositories/container_repo.py apps/backend/routers/container.py apps/backend/tests/unit/routers/test_container_status.py
git commit -m "feat: add last_error/last_error_at to container status endpoint"
```

---

## Task 2: Create `POST /container/recover` endpoint

**Files:**
- Create: `apps/backend/routers/container_recover.py`
- Create: `apps/backend/tests/unit/routers/test_container_recover.py`
- Modify: `apps/backend/main.py`

- [ ] **Step 1: Write tests for the recover endpoint**

Create `apps/backend/tests/unit/routers/test_container_recover.py`:

```python
"""Tests for POST /container/recover endpoint."""

from unittest.mock import AsyncMock, patch

import pytest


class TestContainerRecover:
    """Test POST /api/v1/container/recover."""

    @pytest.fixture
    def mock_ecs_manager(self):
        with patch("routers.container_recover.get_ecs_manager") as mock_getter:
            manager = AsyncMock()
            mock_getter.return_value = manager
            yield manager

    @pytest.fixture
    def mock_container_repo(self):
        with patch("routers.container_recover.container_repo") as mock_repo:
            yield mock_repo

    @pytest.fixture
    def mock_call_gateway_rpc(self):
        with patch("routers.container_recover._call_gateway_rpc", new_callable=AsyncMock) as mock_rpc:
            mock_rpc.return_value = {}
            yield mock_rpc

    # --- CONTAINER_DOWN: full re-provision ---

    @pytest.mark.asyncio
    async def test_recover_stopped_container_reprovisions(
        self, async_client, mock_ecs_manager, mock_container_repo, mock_call_gateway_rpc
    ):
        """Stopped container should trigger full re-provision."""
        mock_ecs_manager.resolve_running_container = AsyncMock(return_value=(None, None))
        mock_ecs_manager.get_service_status = AsyncMock(return_value={
            "owner_id": "user_test_123",
            "status": "stopped",
            "substatus": None,
        })
        mock_ecs_manager.provision_user_container = AsyncMock(return_value="openclaw-new")

        response = await async_client.post("/api/v1/container/recover")
        assert response.status_code == 200
        data = response.json()
        assert data["action"] == "reprovision"
        assert data["state"] == "CONTAINER_DOWN"
        mock_ecs_manager.provision_user_container.assert_called_once()

    @pytest.mark.asyncio
    async def test_recover_error_container_reprovisions(
        self, async_client, mock_ecs_manager, mock_container_repo, mock_call_gateway_rpc
    ):
        """Error container should trigger full re-provision."""
        mock_ecs_manager.resolve_running_container = AsyncMock(return_value=(None, None))
        mock_ecs_manager.get_service_status = AsyncMock(return_value={
            "owner_id": "user_test_123",
            "status": "error",
            "substatus": None,
            "last_error": "OutOfMemoryError",
        })
        mock_ecs_manager.provision_user_container = AsyncMock(return_value="openclaw-new")

        response = await async_client.post("/api/v1/container/recover")
        assert response.status_code == 200
        data = response.json()
        assert data["action"] == "reprovision"
        assert data["state"] == "CONTAINER_DOWN"

    # --- GATEWAY_DOWN: restart gateway ---

    @pytest.mark.asyncio
    async def test_recover_gateway_down_restarts(
        self, async_client, mock_ecs_manager, mock_container_repo, mock_call_gateway_rpc
    ):
        """Running container with unresponsive gateway should restart gateway."""
        container = {
            "owner_id": "user_test_123",
            "gateway_token": "test-token",
            "status": "running",
        }
        mock_ecs_manager.resolve_running_container = AsyncMock(return_value=(container, "10.0.1.5"))
        # Gateway health check fails
        mock_call_gateway_rpc.side_effect = [
            ConnectionRefusedError(),  # health check fails
            {},  # update.run succeeds
        ]

        response = await async_client.post("/api/v1/container/recover")
        assert response.status_code == 200
        data = response.json()
        assert data["action"] == "gateway_restart"
        assert data["state"] == "GATEWAY_DOWN"

    @pytest.mark.asyncio
    async def test_recover_gateway_down_escalates_to_reprovision(
        self, async_client, mock_ecs_manager, mock_container_repo, mock_call_gateway_rpc
    ):
        """If gateway restart fails, escalate to reprovision."""
        container = {
            "owner_id": "user_test_123",
            "gateway_token": "test-token",
            "status": "running",
        }
        mock_ecs_manager.resolve_running_container = AsyncMock(return_value=(container, "10.0.1.5"))
        mock_ecs_manager.provision_user_container = AsyncMock(return_value="openclaw-new")
        # Both health check and restart fail
        mock_call_gateway_rpc.side_effect = ConnectionRefusedError()

        response = await async_client.post("/api/v1/container/recover")
        assert response.status_code == 200
        data = response.json()
        assert data["action"] == "reprovision"

    # --- HEALTHY: no-op ---

    @pytest.mark.asyncio
    async def test_recover_healthy_returns_none(
        self, async_client, mock_ecs_manager, mock_container_repo, mock_call_gateway_rpc
    ):
        """Healthy system should return action=none."""
        container = {
            "owner_id": "user_test_123",
            "gateway_token": "test-token",
            "status": "running",
        }
        mock_ecs_manager.resolve_running_container = AsyncMock(return_value=(container, "10.0.1.5"))
        mock_call_gateway_rpc.return_value = {"ok": True}  # health check passes

        response = await async_client.post("/api/v1/container/recover")
        assert response.status_code == 200
        data = response.json()
        assert data["action"] == "none"
        assert data["state"] == "HEALTHY"

    # --- No container ---

    @pytest.mark.asyncio
    async def test_recover_no_container_returns_404(
        self, async_client, mock_ecs_manager, mock_container_repo, mock_call_gateway_rpc
    ):
        """No container at all should return 404."""
        mock_ecs_manager.resolve_running_container = AsyncMock(return_value=(None, None))
        mock_ecs_manager.get_service_status = AsyncMock(return_value=None)

        response = await async_client.post("/api/v1/container/recover")
        assert response.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && uv run pytest tests/unit/routers/test_container_recover.py -v`

Expected: FAIL — module `routers.container_recover` does not exist.

- [ ] **Step 3: Implement the recover endpoint**

Create `apps/backend/routers/container_recover.py`:

```python
"""Container recovery endpoint.

Single endpoint that inspects current container + gateway state
and dispatches the appropriate recovery action.
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException

from core.auth import AuthContext, get_current_user, resolve_owner_id
from core.containers import get_ecs_manager
from core.containers.ecs_manager import GATEWAY_PORT
from core.repositories import container_repo

logger = logging.getLogger(__name__)

router = APIRouter()

# In-memory per-owner lock to prevent concurrent recovery.
# Safe for single-instance backend. For multi-instance, use DynamoDB conditional writes.
_recovery_locks: dict[str, asyncio.Lock] = {}


def _get_lock(owner_id: str) -> asyncio.Lock:
    if owner_id not in _recovery_locks:
        _recovery_locks[owner_id] = asyncio.Lock()
    return _recovery_locks[owner_id]


async def _call_gateway_rpc(ip: str, token: str, method: str, params: dict | None = None) -> dict:
    """Short-lived WebSocket RPC call to a gateway container."""
    import websockets

    uri = f"ws://{ip}:{GATEWAY_PORT}"
    async with websockets.connect(uri, open_timeout=5, close_timeout=2) as ws:
        # Handshake: wait for challenge, send connect
        import json, uuid

        challenge = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        if challenge.get("event") != "connect.challenge":
            raise RuntimeError("Unexpected handshake message")

        req_id = str(uuid.uuid4())
        await ws.send(json.dumps({
            "type": "req",
            "id": req_id,
            "method": "connect",
            "params": {"token": token},
        }))
        connect_resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        if not connect_resp.get("payload", {}).get("ok"):
            raise RuntimeError("Handshake rejected")

        # Send the actual RPC
        rpc_id = str(uuid.uuid4())
        await ws.send(json.dumps({
            "type": "req",
            "id": rpc_id,
            "method": method,
            "params": params or {},
        }))
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            if msg.get("type") == "res" and msg.get("id") == rpc_id:
                return msg.get("payload", {})


@router.post(
    "/recover",
    summary="Recover container or gateway",
    description=(
        "Inspects current container and gateway state, then takes the "
        "appropriate recovery action. Idempotent and safe to call repeatedly."
    ),
    operation_id="container_recover",
    responses={
        404: {"description": "No container for this user"},
    },
)
async def container_recover(
    auth: AuthContext = Depends(get_current_user),
):
    owner_id = resolve_owner_id(auth)
    lock = _get_lock(owner_id)

    if lock.locked():
        return {
            "action": "already_recovering",
            "state": "RECOVERING",
            "reason": "Recovery already in progress",
        }

    async with lock:
        ecs_manager = get_ecs_manager()

        # 1. Try to resolve a running container
        container, ip = await ecs_manager.resolve_running_container(owner_id)

        if not container:
            # Fall back to get_service_status for stopped/error containers
            container = await ecs_manager.get_service_status(owner_id)

        if not container:
            raise HTTPException(status_code=404, detail="No container found")

        status = container.get("status", "unknown")

        # 2. Container is stopped or error → full re-provision
        if status in ("stopped", "error"):
            reason = container.get("last_error", f"Container is {status}")
            logger.info("Recovering owner %s: reprovision (status=%s)", owner_id, status)
            try:
                await ecs_manager.provision_user_container(owner_id)
            except Exception as e:
                logger.error("Recovery reprovision failed for %s: %s", owner_id, e)
                raise HTTPException(status_code=502, detail="Re-provisioning failed")
            return {
                "action": "reprovision",
                "state": "CONTAINER_DOWN",
                "reason": reason,
            }

        # 3. Container is running → check gateway health
        token = container.get("gateway_token", "")
        if not ip:
            # Running but no IP — shouldn't happen, reprovision
            logger.warning("Owner %s: running container but no IP, reprovisioning", owner_id)
            try:
                await ecs_manager.provision_user_container(owner_id)
            except Exception as e:
                raise HTTPException(status_code=502, detail="Re-provisioning failed")
            return {
                "action": "reprovision",
                "state": "CONTAINER_DOWN",
                "reason": "Container running but unreachable",
            }

        # Try gateway health check
        try:
            health = await _call_gateway_rpc(ip, token, "health")
            if health.get("ok"):
                return {
                    "action": "none",
                    "state": "HEALTHY",
                    "reason": "System is healthy",
                }
        except Exception:
            pass  # Gateway is down, proceed to restart

        # 4. Gateway is down → try restart via update.run RPC
        logger.info("Recovering owner %s: gateway restart", owner_id)
        try:
            await _call_gateway_rpc(ip, token, "update.run")
            return {
                "action": "gateway_restart",
                "state": "GATEWAY_DOWN",
                "reason": "Gateway not responding — restarting",
            }
        except Exception:
            # Gateway restart failed — escalate to reprovision
            logger.warning("Owner %s: gateway restart failed, escalating to reprovision", owner_id)
            await container_repo.update_error(owner_id, "Gateway restart failed — reprovisioning")
            try:
                await ecs_manager.provision_user_container(owner_id)
            except Exception as e:
                raise HTTPException(status_code=502, detail="Re-provisioning failed")
            return {
                "action": "reprovision",
                "state": "GATEWAY_DOWN",
                "reason": "Gateway restart failed — reprovisioning",
            }
```

- [ ] **Step 4: Register the router in main.py**

In `apps/backend/main.py`, find where routers are registered (look for `app.include_router` calls for `container_rpc`). Add:

```python
from routers.container_recover import router as container_recover_router

app.include_router(container_recover_router, prefix="/api/v1/container", tags=["container"])
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd apps/backend && uv run pytest tests/unit/routers/test_container_recover.py -v`

Expected: All PASS.

- [ ] **Step 6: Run full backend test suite**

Run: `cd apps/backend && uv run pytest tests/ -v --timeout=30`

Expected: All PASS — no regressions.

- [ ] **Step 7: Commit**

```bash
git add apps/backend/routers/container_recover.py apps/backend/tests/unit/routers/test_container_recover.py apps/backend/main.py
git commit -m "feat: add POST /container/recover endpoint with state-aware recovery"
```

---

## Task 3: Emit `status_change` push events from connection pool

**Files:**
- Modify: `apps/backend/core/gateway/connection_pool.py`
- Modify: `apps/backend/tests/unit/core/test_connection_pool.py`

- [ ] **Step 1: Write test for status_change event emission**

In `apps/backend/tests/unit/core/test_connection_pool.py`, add a test (follow existing test patterns in that file). The test should verify that when a gateway connection is established or lost, a `status_change` event is sent to frontend connections via the management API:

```python
class TestStatusChangeEvents:
    """Test that gateway connect/disconnect emits status_change events."""

    @pytest.mark.asyncio
    async def test_emits_connected_event_on_gateway_connect(self):
        """Should push status_change with state=HEALTHY when gateway connects."""
        mock_mgmt = MagicMock()
        mock_mgmt.send_message = MagicMock(return_value=True)

        conn = GatewayConnection(
            user_id="user_123",
            ip="10.0.1.5",
            token="test-token",
            management_api=mock_mgmt,
            usage_callback=AsyncMock(),
        )
        conn._frontend_connections = {"conn_abc"}

        conn._emit_status_change("HEALTHY", "Gateway connected")

        mock_mgmt.send_message.assert_called_once()
        call_args = mock_mgmt.send_message.call_args
        assert call_args[0][0] == "conn_abc"
        msg = json.loads(call_args[0][1]) if isinstance(call_args[0][1], str) else call_args[0][1]
        assert msg["type"] == "event"
        assert msg["event"] == "status_change"
        assert msg["payload"]["state"] == "HEALTHY"
        assert msg["payload"]["reason"] == "Gateway connected"

    @pytest.mark.asyncio
    async def test_emits_down_event_on_gateway_disconnect(self):
        """Should push status_change with state=GATEWAY_DOWN when gateway disconnects."""
        mock_mgmt = MagicMock()
        mock_mgmt.send_message = MagicMock(return_value=True)

        conn = GatewayConnection(
            user_id="user_123",
            ip="10.0.1.5",
            token="test-token",
            management_api=mock_mgmt,
            usage_callback=AsyncMock(),
        )
        conn._frontend_connections = {"conn_abc", "conn_def"}

        conn._emit_status_change("GATEWAY_DOWN", "Gateway connection lost")

        assert mock_mgmt.send_message.call_count == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && uv run pytest tests/unit/core/test_connection_pool.py::TestStatusChangeEvents -v`

Expected: FAIL — `_emit_status_change` method does not exist.

- [ ] **Step 3: Add `_emit_status_change` to GatewayConnection**

In `apps/backend/core/gateway/connection_pool.py`, add a method to the `GatewayConnection` class (after the existing `_forward_to_frontends` method or similar):

```python
def _emit_status_change(self, state: str, reason: str) -> None:
    """Push a status_change event to all connected frontend WebSockets."""
    import json
    from datetime import datetime, timezone

    # Wrap as {type: "event"} so the frontend WS router in useGateway
    # delivers it to onEvent subscribers (unrecognized types are dropped).
    message = {
        "type": "event",
        "event": "status_change",
        "payload": {
            "state": state,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    }
    payload = json.dumps(message)
    for conn_id in list(self._frontend_connections):
        try:
            self._management_api.send_message(conn_id, payload)
        except Exception:
            logger.debug("Failed to push status_change to %s", conn_id)
```

- [ ] **Step 4: Call `_emit_status_change` on connect and disconnect**

In the `connect()` method of `GatewayConnection`, after the health check succeeds (after `self._healthy = True` or equivalent), add:

```python
self._emit_status_change("HEALTHY", "Gateway connected")
```

In the `_reader_loop()` method, in the `except` / `finally` block where the connection is marked as closed (look for where `self._connected = False` or the WS closes), add:

```python
self._emit_status_change("GATEWAY_DOWN", "Gateway connection lost")
```

Also in the `close()` method, before cleanup:

```python
self._emit_status_change("GATEWAY_DOWN", "Gateway connection closed")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd apps/backend && uv run pytest tests/unit/core/test_connection_pool.py::TestStatusChangeEvents -v`

Expected: All PASS.

- [ ] **Step 6: Run full connection pool tests**

Run: `cd apps/backend && uv run pytest tests/unit/core/test_connection_pool.py -v`

Expected: All PASS — no regressions.

- [ ] **Step 7: Commit**

```bash
git add apps/backend/core/gateway/connection_pool.py apps/backend/tests/unit/core/test_connection_pool.py
git commit -m "feat: emit status_change push events on gateway connect/disconnect"
```

---

## Task 4: Update `useContainerStatus` type and create `useSystemHealth` hook

**Files:**
- Modify: `apps/frontend/src/hooks/useContainerStatus.ts`
- Create: `apps/frontend/src/hooks/useSystemHealth.ts`

- [ ] **Step 1: Add `last_error` fields to ContainerStatus type**

In `apps/frontend/src/hooks/useContainerStatus.ts`, update the `ContainerStatus` interface (lines 8-15):

```typescript
export interface ContainerStatus {
  service_name: string;
  status: string;
  substatus: string | null;
  created_at: string | null;
  updated_at: string | null;
  region: string;
  last_error: string | null;
  last_error_at: string | null;
}
```

- [ ] **Step 2: Create the `useSystemHealth` hook**

Create `apps/frontend/src/hooks/useSystemHealth.ts`:

```typescript
"use client";

import { useEffect, useState, useCallback } from "react";
import { useGateway } from "@/hooks/useGateway";
import { useGatewayRpc } from "@/hooks/useGatewayRpc";
import { useContainerStatus } from "@/hooks/useContainerStatus";
import { useApi } from "@/lib/api";

export type HealthState =
  | "HEALTHY"
  | "STARTING"
  | "RECOVERING"
  | "GATEWAY_DOWN"
  | "CONTAINER_DOWN";

interface HealthData {
  ok?: boolean;
}

export interface SystemHealth {
  state: HealthState;
  reason: string;
  /** Whether a recovery action is available */
  canRecover: boolean;
  /** Label for the recovery button */
  actionLabel: string | null;
  /** Call to trigger recovery */
  recover: () => Promise<RecoverResponse | null>;
  /** Whether recovery is in progress */
  isRecovering: boolean;
}

interface RecoverResponse {
  action: "reprovision" | "gateway_restart" | "none" | "already_recovering";
  state: string;
  reason: string;
}

const MAX_RECONNECT = 10;

export function useSystemHealth(): SystemHealth {
  const { isConnected, reconnectAttempt } = useGateway();
  const { container } = useContainerStatus({
    refreshInterval: 10_000,
    enabled: true,
  });

  // Gateway health RPC — only when WS connected
  const { data: health } = useGatewayRpc<HealthData>("health", undefined, {
    refreshInterval: isConnected ? 5_000 : 0,
    enabled: isConnected,
  });

  const [isRecovering, setIsRecovering] = useState(false);
  const [pushState, setPushState] = useState<{ state: string; reason: string } | null>(null);
  const api = useApi();

  // Listen for push status_change events via WS
  // Backend sends: {type: "event", event: "status_change", payload: {state, reason}}
  const { onEvent } = useGateway();
  useEffect(() => {
    const unsub = onEvent((event) => {
      if (event.event === "status_change" && event.payload) {
        setPushState({
          state: event.payload.state as string,
          reason: event.payload.reason as string,
        });
        // Clear push state after 15s (let polling take over)
        setTimeout(() => setPushState(null), 15_000);
      }
    });
    return unsub;
  }, [onEvent]);

  // Derive state (first match wins)
  let state: HealthState;
  let reason: string;

  // Push events take priority for immediate transitions
  if (pushState) {
    state = pushState.state as HealthState;
    reason = pushState.reason;
  } else if (!container) {
    state = "STARTING";
    reason = "Loading container status...";
  } else if (container.status === "provisioning") {
    state = "STARTING";
    reason = container.substatus === "auto_retry"
      ? "Restarting container..."
      : "Container provisioning — waiting for ECS task";
  } else if (container.status === "stopped" || container.status === "error") {
    state = "CONTAINER_DOWN";
    reason = container.last_error
      ?? `Container is ${container.status}`;
  } else if (!isConnected && reconnectAttempt > 0 && reconnectAttempt < MAX_RECONNECT) {
    state = "RECOVERING";
    reason = `Reconnecting... attempt ${reconnectAttempt} of ${MAX_RECONNECT}`;
  } else if (!isConnected && container.status === "running") {
    state = "GATEWAY_DOWN";
    reason = "Gateway not responding";
  } else if (isConnected && health && !health.ok) {
    state = "GATEWAY_DOWN";
    reason = "Gateway health check failing";
  } else {
    state = "HEALTHY";
    reason = "Connected";
  }

  // Recovery action
  const canRecover = state === "GATEWAY_DOWN" || state === "CONTAINER_DOWN";
  const actionLabel =
    state === "CONTAINER_DOWN"
      ? "Restart Agent"
      : state === "GATEWAY_DOWN"
        ? "Restart Gateway"
        : null;

  const recover = useCallback(async (): Promise<RecoverResponse | null> => {
    if (isRecovering) return null;
    setIsRecovering(true);
    try {
      const resp = await api.post<RecoverResponse>("/container/recover");
      return resp;
    } catch {
      return null;
    } finally {
      // Keep recovering state for 5s to debounce spam clicks
      setTimeout(() => setIsRecovering(false), 5_000);
    }
  }, [api, isRecovering]);

  return {
    state,
    reason,
    canRecover,
    actionLabel,
    recover,
    isRecovering,
  };
}
```

- [ ] **Step 3: Verify the hook compiles**

Run: `cd apps/frontend && pnpm run lint`

Expected: No errors related to `useSystemHealth.ts` or `useContainerStatus.ts`.

- [ ] **Step 4: Commit**

```bash
git add apps/frontend/src/hooks/useContainerStatus.ts apps/frontend/src/hooks/useSystemHealth.ts
git commit -m "feat: add useSystemHealth hook with unified 5-state health model"
```

---

## Task 5: Create `HealthIndicator` component

**Files:**
- Create: `apps/frontend/src/components/chat/HealthIndicator.tsx`

- [ ] **Step 1: Create the HealthIndicator component**

Create `apps/frontend/src/components/chat/HealthIndicator.tsx`:

```tsx
"use client";

import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { useSystemHealth, type HealthState } from "@/hooks/useSystemHealth";
import { Button } from "@/components/ui/button";

const DOT_STYLES: Record<HealthState, string> = {
  HEALTHY: "bg-[#2d8a4e]",
  STARTING: "bg-yellow-500 animate-pulse",
  RECOVERING: "bg-yellow-500 animate-pulse",
  GATEWAY_DOWN: "bg-red-500",
  CONTAINER_DOWN: "bg-red-500",
};

const LABEL_STYLES: Record<HealthState, string> = {
  HEALTHY: "text-[#8a8578]",
  STARTING: "text-yellow-600",
  RECOVERING: "text-yellow-600",
  GATEWAY_DOWN: "text-red-500",
  CONTAINER_DOWN: "text-red-500",
};

export function HealthIndicator({
  onRecoveryReprovision,
}: {
  /** Called when recovery triggers a reprovision, so parent can show ProvisioningStepper */
  onRecoveryReprovision?: () => void;
}) {
  const {
    state,
    reason,
    canRecover,
    actionLabel,
    recover,
    isRecovering,
  } = useSystemHealth();

  const handleRecover = async () => {
    const result = await recover();
    if (result?.action === "reprovision" && onRecoveryReprovision) {
      onRecoveryReprovision();
    }
  };

  return (
    <div
      className={cn(
        "flex items-center gap-2 px-3 py-2 rounded-md text-xs",
        state === "HEALTHY" ? "opacity-80" : "opacity-100",
      )}
      title={reason}
    >
      {/* Status dot */}
      <span
        className={cn("h-2 w-2 rounded-full shrink-0", DOT_STYLES[state])}
      />

      {/* Label */}
      <span className={cn("truncate flex-1", LABEL_STYLES[state])}>
        {state === "HEALTHY"
          ? "Connected"
          : state === "RECOVERING"
            ? reason
            : state === "STARTING"
              ? "Starting..."
              : reason}
      </span>

      {/* Action button */}
      {isRecovering ? (
        <Loader2 className="h-3 w-3 animate-spin text-[#8a8578]" />
      ) : canRecover && actionLabel ? (
        <Button
          variant="ghost"
          size="sm"
          onClick={handleRecover}
          className="h-5 px-2 text-[10px] font-medium hover:bg-[#e8e4db]"
        >
          {actionLabel}
        </Button>
      ) : null}
    </div>
  );
}
```

- [ ] **Step 2: Verify it compiles**

Run: `cd apps/frontend && pnpm run lint`

Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add apps/frontend/src/components/chat/HealthIndicator.tsx
git commit -m "feat: add HealthIndicator component with status dot and Fix It button"
```

---

## Task 6: Wire HealthIndicator into Sidebar, remove ConnectionStatusBar

**Files:**
- Modify: `apps/frontend/src/components/chat/Sidebar.tsx`
- Modify: `apps/frontend/src/components/chat/AgentChatWindow.tsx`

- [ ] **Step 1: Add HealthIndicator to Sidebar**

In `apps/frontend/src/components/chat/Sidebar.tsx`:

Add import at the top:

```typescript
import { HealthIndicator } from "@/components/chat/HealthIndicator";
```

Find the sidebar content area — the div that contains the tab switcher and lists. Add the `HealthIndicator` right above the tab switcher (before the chats/agents tabs, approximately line 61). The component accepts an optional `onRecoveryReprovision` callback — thread it through from props.

First, add to the `SidebarProps` interface:

```typescript
onRecoveryReprovision?: () => void;
```

Then render it in the component body, before the tab switcher:

```tsx
<HealthIndicator onRecoveryReprovision={onRecoveryReprovision} />
```

- [ ] **Step 2: Remove ConnectionStatusBar from AgentChatWindow**

In `apps/frontend/src/components/chat/AgentChatWindow.tsx`:

Remove the import of `ConnectionStatusBar` (line that says `import { ConnectionStatusBar } from "./ConnectionStatusBar"`).

Find where `<ConnectionStatusBar />` is rendered in the JSX (search for `ConnectionStatusBar` in the return statement) and remove that line entirely.

- [ ] **Step 3: Verify it compiles**

Run: `cd apps/frontend && pnpm run lint`

Expected: No errors. You may get unused import warnings for things `ConnectionStatusBar` was using — clean those up if they occur.

- [ ] **Step 4: Commit**

```bash
git add apps/frontend/src/components/chat/Sidebar.tsx apps/frontend/src/components/chat/AgentChatWindow.tsx
git commit -m "feat: wire HealthIndicator into Sidebar, remove ConnectionStatusBar"
```

---

## Task 7: Add `trigger` prop to ProvisioningStepper for recovery flow

**Files:**
- Modify: `apps/frontend/src/components/chat/ProvisioningStepper.tsx`

- [ ] **Step 1: Add trigger prop**

In `apps/frontend/src/components/chat/ProvisioningStepper.tsx`, the component currently takes no explicit props (it reads everything from hooks). Add a `trigger` prop:

Find the component definition (line ~37):

```tsx
export function ProvisioningStepper() {
```

Change to:

```tsx
export function ProvisioningStepper({
  trigger = "onboarding",
}: {
  /** "onboarding" = full flow (billing → container → gateway → channels → ready).
   *  "recovery" = skip billing, start from container provisioning. */
  trigger?: "onboarding" | "recovery";
}) {
```

- [ ] **Step 2: Skip billing phase for recovery trigger**

Find the phase derivation logic (approximately lines 98-122, where it checks billing status and sets phase to "payment"). Wrap the billing check:

Find the line that sets phase to `"payment"` when user has no subscription. Add a guard:

```typescript
// Skip billing check when triggered by recovery — user already has a plan
if (trigger === "recovery") {
  // Start directly from container phase
} else if (/* existing billing check */) {
  // existing payment phase logic
}
```

The exact edit depends on the current phase derivation, but the goal is: when `trigger === "recovery"`, never set phase to `"payment"` — go straight to `"container"`.

- [ ] **Step 3: Verify it compiles**

Run: `cd apps/frontend && pnpm run lint`

Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add apps/frontend/src/components/chat/ProvisioningStepper.tsx
git commit -m "feat: add trigger prop to ProvisioningStepper for recovery flow"
```

---

## Task 8: Simplify OverviewPanel — remove action buttons, add health summary

**Files:**
- Modify: `apps/frontend/src/components/control/panels/OverviewPanel.tsx`

- [ ] **Step 1: Remove GatewayActions and ActionButton components**

In `apps/frontend/src/components/control/panels/OverviewPanel.tsx`:

Remove the `GatewayActions` sub-component (lines ~341-446) and the `ActionButton` sub-component (lines ~448-476) entirely.

Remove the `useGatewayRpcMutation` import if no longer used.

- [ ] **Step 2: Add health summary card**

Replace the `<GatewayActions>` render call (in the `OverviewPanel` component body) with a health summary card using the `useSystemHealth` hook:

Add import at the top:

```typescript
import { useSystemHealth } from "@/hooks/useSystemHealth";
```

In the `OverviewPanel` component body, add:

```typescript
const { state, reason, canRecover, actionLabel, recover, isRecovering } = useSystemHealth();
```

Replace the GatewayActions render with:

```tsx
{/* Health Summary */}
<div className="rounded-lg border border-[#d5d0c7] bg-[#f3efe6] p-4">
  <div className="flex items-center justify-between">
    <div className="flex items-center gap-2">
      <span
        className={cn(
          "h-2.5 w-2.5 rounded-full",
          state === "HEALTHY" ? "bg-[#2d8a4e]" :
          state === "STARTING" || state === "RECOVERING" ? "bg-yellow-500 animate-pulse" :
          "bg-red-500"
        )}
      />
      <span className="text-sm font-medium text-[#1a1a1a]">
        {state === "HEALTHY" ? "System Healthy" :
         state === "STARTING" ? "Starting..." :
         state === "RECOVERING" ? "Recovering..." :
         state === "GATEWAY_DOWN" ? "Gateway Down" :
         "Container Down"}
      </span>
    </div>
    {canRecover && actionLabel && (
      <Button
        variant="outline"
        size="sm"
        onClick={recover}
        disabled={isRecovering}
        className="text-xs"
      >
        {isRecovering ? (
          <Loader2 className="h-3 w-3 animate-spin mr-1" />
        ) : null}
        {actionLabel}
      </Button>
    )}
  </div>
  <p className="text-xs text-[#8a8578] mt-1">{reason}</p>
</div>
```

- [ ] **Step 3: Clean up unused imports**

Remove any imports that were only used by the deleted `GatewayActions` and `ActionButton` components (e.g., `RotateCcw`, `Download`, `Radio` from lucide-react, `useGatewayRpcMutation`). Keep icons still used elsewhere.

- [ ] **Step 4: Verify it compiles**

Run: `cd apps/frontend && pnpm run lint`

Expected: No errors.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/components/control/panels/OverviewPanel.tsx
git commit -m "feat: replace OverviewPanel action buttons with health summary card"
```

---

## Task 9: Delete ConnectionStatusBar and run full test suite

**Files:**
- Delete: `apps/frontend/src/components/chat/ConnectionStatusBar.tsx`

- [ ] **Step 1: Delete ConnectionStatusBar**

Delete the file `apps/frontend/src/components/chat/ConnectionStatusBar.tsx`.

- [ ] **Step 2: Search for any remaining imports of ConnectionStatusBar**

Search the codebase for `ConnectionStatusBar` to ensure no other file still imports it. If any do, remove those imports.

Run: grep for `ConnectionStatusBar` across `apps/frontend/src/`.

- [ ] **Step 3: Run frontend lint**

Run: `cd apps/frontend && pnpm run lint`

Expected: No errors.

- [ ] **Step 4: Run frontend build**

Run: `cd apps/frontend && pnpm run build`

Expected: Build succeeds.

- [ ] **Step 5: Run backend tests**

Run: `cd apps/backend && uv run pytest tests/ -v --timeout=30`

Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git rm apps/frontend/src/components/chat/ConnectionStatusBar.tsx
git add -A apps/frontend/src/
git commit -m "chore: remove ConnectionStatusBar, replaced by HealthIndicator"
```

---

## Verification Checklist

After all tasks are complete:

- [ ] `POST /container/recover` returns correct action for each state (stopped, error, gateway down, healthy)
- [ ] `GET /container/status` includes `last_error` and `last_error_at` fields
- [ ] Gateway connect/disconnect emits `status_change` push events to frontend WS connections
- [ ] `useSystemHealth` correctly derives 5 states from container + gateway + WS signals
- [ ] Sidebar shows persistent colored dot with correct state
- [ ] "Fix it" button shows correct label per state and triggers recovery
- [ ] Recovery for `CONTAINER_DOWN` transitions to `ProvisioningStepper`
- [ ] OverviewPanel shows health summary instead of 4 action buttons
- [ ] `ConnectionStatusBar.tsx` is deleted with no remaining imports
- [ ] All backend tests pass
- [ ] Frontend builds successfully
