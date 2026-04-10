# Desktop Per-User Node Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the desktop app's local tool execution work per-user for both personal and org accounts, using OpenClaw's `execNode` session field to pin each user's agent sessions to their own Mac.

**Architecture:** The backend tracks per-user node connections (not just per-owner). When a user with a connected Mac sends a chat message, the backend calls `sessions.patch` (once per session) to set `execNode` and `execHost: "node"`, so the agent's exec tool routes commands to that user's Mac. Broadcasting and config patching are scoped per-user with reference counting.

**Tech Stack:** Python (FastAPI backend), Rust (Tauri desktop app), TypeScript (Next.js frontend), OpenClaw gateway protocol

**Spec:** `docs/superpowers/specs/2026-04-12-desktop-per-user-node-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `apps/backend/core/gateway/connection_pool.py` | Modify | Add `broadcast_to_member()` for per-user event delivery |
| `apps/backend/routers/node_proxy.py` | Modify | Per-user node tracking, ref-counted config patches, per-user broadcasts |
| `apps/backend/routers/websocket_chat.py` | Modify | Pass `user_id` to node handlers; `sessions.patch` before `chat.send` |
| `apps/backend/core/gateway/node_connection.py` | Modify | Expose `device_id` attribute after connect for per-user tracking |
| `apps/backend/tests/unit/routers/test_node_proxy.py` | Create | Unit tests for per-user node tracking |
| `.worktrees/feat-desktop-app/apps/desktop/src-tauri/src/lib.rs` | Modify | Accept `display_name` + `user_id` in IPC; remove proxy; add file logger |
| `.worktrees/feat-desktop-app/apps/desktop/src-tauri/src/node_client.rs` | Modify | Fix `client.id` to `"node-host"` |
| `apps/frontend/src/hooks/useGateway.tsx` | Modify | Pass user display name + ID in Tauri IPC |

---

### Task 1: Add `broadcast_to_member` to the connection pool

**Files:**
- Modify: `apps/backend/core/gateway/connection_pool.py:866-870`

- [ ] **Step 1: Add the `broadcast_to_member` method**

Add below the existing `broadcast_to_user` method (line 870):

```python
async def broadcast_to_member(
    self, owner_id: str, member_user_id: str, message: dict
) -> None:
    """Send a message to frontend connections for a specific org member.

    For personal accounts (owner_id == member_user_id), this behaves
    identically to broadcast_to_user. For org accounts, it filters to
    only the connections belonging to *member_user_id*.
    """
    conn = self._connections.get(owner_id)
    if not conn:
        return
    # Personal account — no per-member filtering needed
    if owner_id == member_user_id:
        conn._forward_to_frontends(message)
        return
    # Org account — filter to this member's connections only
    gone: list[str] = []
    for conn_id in list(conn._frontend_connections):
        member = conn._conn_member_map.get(conn_id, "")
        if member.lower() != member_user_id.lower():
            continue
        try:
            if not self._management_api.send_message(conn_id, message):
                gone.append(conn_id)
        except Exception:
            gone.append(conn_id)
    for conn_id in gone:
        conn._frontend_connections.discard(conn_id)
```

- [ ] **Step 2: Run existing tests to verify no regressions**

Run: `cd apps/backend && CLERK_ISSUER=https://up-moth-55.clerk.accounts.dev uv run pytest tests/unit/core/test_connection_pool.py -q --no-cov`
Expected: All existing tests pass.

- [ ] **Step 3: Commit**

```bash
git add apps/backend/core/gateway/connection_pool.py
git commit -m "feat: add broadcast_to_member for per-user node status delivery"
```

---

### Task 2: Per-user node tracking in `node_proxy.py`

**Files:**
- Modify: `apps/backend/routers/node_proxy.py`
- Create: `apps/backend/tests/unit/routers/test_node_proxy.py`

- [ ] **Step 1: Write tests for the new per-user tracking**

Create `apps/backend/tests/unit/routers/test_node_proxy.py`:

```python
"""Tests for per-user node connection tracking."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from routers.node_proxy import (
    handle_node_connect,
    handle_node_disconnect,
    get_user_node,
    is_node_connection,
    _user_nodes,
    _node_count,
    _node_upstreams,
)


@pytest.fixture(autouse=True)
def clear_module_state():
    """Reset module-level dicts between tests."""
    _user_nodes.clear()
    _node_count.clear()
    _node_upstreams.clear()
    yield
    _user_nodes.clear()
    _node_count.clear()
    _node_upstreams.clear()


@pytest.fixture
def mock_ecs():
    with patch("routers.node_proxy.get_ecs_manager") as m:
        ecs = AsyncMock()
        ecs.resolve_running_container = AsyncMock(
            return_value=({"gateway_token": "tok123"}, "10.0.1.1")
        )
        m.return_value = ecs
        yield ecs


@pytest.fixture
def mock_pool():
    with patch("routers.node_proxy.get_gateway_pool") as m:
        pool = MagicMock()
        pool.broadcast_to_member = AsyncMock()
        m.return_value = pool
        yield pool


@pytest.fixture
def mock_upstream():
    with patch("routers.node_proxy.NodeUpstreamConnection") as cls:
        upstream = AsyncMock()
        upstream.connect = AsyncMock(return_value={"ok": True, "payload": {"protocol": 3}})
        upstream.start_reader = AsyncMock()
        upstream.close = AsyncMock()
        cls.return_value = upstream
        yield upstream


@pytest.fixture
def mock_config_patcher():
    with patch("routers.node_proxy.patch_openclaw_config", new_callable=AsyncMock) as m:
        yield m


@pytest.mark.asyncio
async def test_connect_stores_user_node(mock_ecs, mock_pool, mock_upstream, mock_config_patcher):
    """handle_node_connect stores the user_id -> nodeId mapping."""
    mgmt = MagicMock()

    await handle_node_connect(
        owner_id="org_123",
        user_id="user_alice",
        connection_id="conn_1",
        connect_params={"role": "node", "client": {"id": "node-host"}},
        management_api=mgmt,
    )

    assert "user_alice" in _user_nodes
    assert _user_nodes["user_alice"]["connection_id"] == "conn_1"


@pytest.mark.asyncio
async def test_connect_increments_node_count(mock_ecs, mock_pool, mock_upstream, mock_config_patcher):
    """First node connection for an owner patches config to enable node tools."""
    mgmt = MagicMock()

    await handle_node_connect(
        owner_id="org_123", user_id="user_alice",
        connection_id="conn_1", connect_params={}, management_api=mgmt,
    )
    assert _node_count.get("org_123") == 1
    mock_config_patcher.assert_called_once()  # config patched on 0->1

    mock_config_patcher.reset_mock()
    await handle_node_connect(
        owner_id="org_123", user_id="user_bob",
        connection_id="conn_2", connect_params={}, management_api=mgmt,
    )
    assert _node_count.get("org_123") == 2
    mock_config_patcher.assert_not_called()  # no re-patch on 1->2


@pytest.mark.asyncio
async def test_disconnect_decrements_and_patches_on_zero(
    mock_ecs, mock_pool, mock_upstream, mock_config_patcher,
):
    """Config is re-disabled only when the last node disconnects."""
    mgmt = MagicMock()

    # Connect two users
    await handle_node_connect(
        owner_id="org_123", user_id="user_alice",
        connection_id="conn_1", connect_params={}, management_api=mgmt,
    )
    await handle_node_connect(
        owner_id="org_123", user_id="user_bob",
        connection_id="conn_2", connect_params={}, management_api=mgmt,
    )
    mock_config_patcher.reset_mock()

    # Disconnect Alice — count goes 2->1, no config patch
    await handle_node_disconnect("conn_1", "org_123", "user_alice")
    assert _node_count.get("org_123") == 1
    mock_config_patcher.assert_not_called()

    # Disconnect Bob — count goes 1->0, config patched
    await handle_node_disconnect("conn_2", "org_123", "user_bob")
    assert _node_count.get("org_123", 0) == 0
    mock_config_patcher.assert_called_once()


@pytest.mark.asyncio
async def test_disconnect_broadcasts_to_member(
    mock_ecs, mock_pool, mock_upstream, mock_config_patcher,
):
    """Disconnect broadcasts node_status to the specific user, not the whole org."""
    mgmt = MagicMock()
    await handle_node_connect(
        owner_id="org_123", user_id="user_alice",
        connection_id="conn_1", connect_params={}, management_api=mgmt,
    )
    mock_pool.broadcast_to_member.reset_mock()

    await handle_node_disconnect("conn_1", "org_123", "user_alice")

    mock_pool.broadcast_to_member.assert_called_once_with(
        "org_123", "user_alice",
        {"type": "node_status", "status": "disconnected"},
    )


@pytest.mark.asyncio
async def test_get_user_node_returns_none_when_disconnected(
    mock_ecs, mock_pool, mock_upstream, mock_config_patcher,
):
    """get_user_node returns None for users without a connected node."""
    assert get_user_node("user_nobody") is None
```

- [ ] **Step 2: Run tests — they should fail (functions don't exist yet)**

Run: `cd apps/backend && CLERK_ISSUER=https://up-moth-55.clerk.accounts.dev uv run pytest tests/unit/routers/test_node_proxy.py -v --no-cov`
Expected: ImportError or AttributeError (new functions/dicts not defined yet).

- [ ] **Step 3: Expose `device_id` on `NodeUpstreamConnection`**

In `apps/backend/core/gateway/node_connection.py`, add a `device_id` attribute that gets set during `connect()`. In the `__init__` method (line 74), add:

```python
self.device_id: str | None = None
```

In the `connect()` method, after `_build_device_identity` is called (around line 123), store it:

```python
device = _build_device_identity(private_key, nonce, self.node_connect_params)
self.device_id = device["id"]  # SHA-256 hex of Ed25519 public key
```

This lets `handle_node_connect` read `upstream.device_id` after the handshake completes.

- [ ] **Step 4: Rewrite `node_proxy.py` with per-user tracking**

Replace the full content of `apps/backend/routers/node_proxy.py`:

```python
"""
Node connection proxy — per-user tracking for local tool execution.

Manages dedicated upstream WebSocket connections for node clients.
Each connected desktop app gets its own NodeUpstreamConnection to the
shared container. Tracking is per-user (not per-owner) so that in an
org, Alice's Mac and Bob's Mac are independent.

State:
  _node_upstreams   connection_id -> NodeUpstreamConnection
  _user_nodes       user_id -> {nodeId, connection_id, owner_id}
  _node_count       owner_id -> int (active node connections)
  _patched_sessions session_key -> nodeId (in-memory cache)
"""

import logging

from core.gateway.node_connection import NodeUpstreamConnection
from core.containers import get_ecs_manager, get_gateway_pool
from core.config import settings
from core.services.config_patcher import patch_openclaw_config

logger = logging.getLogger(__name__)

# connection_id -> NodeUpstreamConnection
_node_upstreams: dict[str, NodeUpstreamConnection] = {}

# user_id -> {nodeId: str, connection_id: str, owner_id: str}
_user_nodes: dict[str, dict] = {}

# owner_id -> count of active node connections (for ref-counted config patching)
_node_count: dict[str, int] = {}

# session_key -> nodeId (tracks which sessions have been patched with execNode)
_patched_sessions: dict[str, str] = {}


def get_user_node(user_id: str) -> dict | None:
    """Return the node info for a user, or None if not connected."""
    return _user_nodes.get(user_id)


def get_patched_session(session_key: str) -> str | None:
    """Return the nodeId a session is patched with, or None."""
    return _patched_sessions.get(session_key)


def set_patched_session(session_key: str, node_id: str) -> None:
    """Record that a session has been patched with execNode."""
    _patched_sessions[session_key] = node_id


def clear_patched_sessions_for_user(user_id: str) -> list[str]:
    """Remove all patched-session entries for a user. Returns the cleared session keys."""
    cleared = []
    for sk, nid in list(_patched_sessions.items()):
        # Session keys for org members: agent:<agentId>:<userId>
        # We match on the userId segment
        if sk.endswith(f":{user_id}"):
            del _patched_sessions[sk]
            cleared.append(sk)
    return cleared


async def handle_node_connect(
    owner_id: str,
    user_id: str,
    connection_id: str,
    connect_params: dict,
    management_api,
    display_name: str = "Desktop",
) -> dict | None:
    """
    Open a dedicated upstream to the container, complete the node handshake,
    and set up bidirectional relay. Returns the hello-ok dict on success.
    """
    ecs = get_ecs_manager()
    container, ip = await ecs.resolve_running_container(owner_id)

    # Inject user display name into connect params for node.list identification
    client_params = connect_params.get("client", {})
    client_params["displayName"] = f"{display_name} | Isol8 Desktop"
    connect_params["client"] = client_params

    upstream = NodeUpstreamConnection(
        user_id=owner_id,
        container_ip=ip,
        node_connect_params=connect_params,
        efs_mount_path=settings.EFS_MOUNT_PATH,
        gateway_token=container["gateway_token"],
    )

    async def on_upstream_message(data: dict):
        management_api.send_message(connection_id, data)

    upstream.set_message_callback(on_upstream_message)

    hello = await upstream.connect()
    await upstream.start_reader()

    _node_upstreams[connection_id] = upstream

    # The nodeId in OpenClaw's NodeRegistry is the device.id (SHA-256 hex of
    # the Ed25519 public key), set during the connect handshake inside
    # NodeUpstreamConnection.connect(). Read it back from the upstream.
    node_id = upstream.device_id or connection_id

    # Store per-user mapping
    _user_nodes[user_id] = {
        "nodeId": node_id,
        "connection_id": connection_id,
        "owner_id": owner_id,
    }

    # Reference-counted config patching: enable node tools on first connect
    prev_count = _node_count.get(owner_id, 0)
    _node_count[owner_id] = prev_count + 1
    if prev_count == 0:
        await patch_openclaw_config(owner_id, {"tools": {"deny": ["canvas"]}})

    # Per-user broadcast
    pool = get_gateway_pool()
    await pool.broadcast_to_member(
        owner_id, user_id,
        {"type": "node_status", "status": "connected"},
    )

    logger.info(
        "Node proxy established: user=%s owner=%s conn=%s nodeId=%s",
        user_id, owner_id, connection_id, node_id,
    )
    return hello


async def handle_node_message(connection_id: str, message: dict) -> None:
    """Relay a message from the node client to the upstream container."""
    upstream = _node_upstreams.get(connection_id)
    if upstream:
        await upstream.relay_to_upstream(message)
    else:
        logger.warning("No node upstream for connection %s", connection_id)


async def handle_node_disconnect(
    connection_id: str, owner_id: str, user_id: str,
) -> None:
    """Close the upstream connection and update per-user tracking."""
    upstream = _node_upstreams.pop(connection_id, None)
    if upstream:
        await upstream.close()

    # Remove per-user mapping
    node_info = _user_nodes.pop(user_id, None)

    # Clear patched sessions for this user (we'll clear execNode on them below)
    cleared_sessions = clear_patched_sessions_for_user(user_id)
    if cleared_sessions:
        pool = get_gateway_pool()
        # Best-effort: clear execNode on sessions. If container is down, skip.
        for sk in cleared_sessions:
            try:
                container, ip = await get_ecs_manager().resolve_running_container(owner_id)
                await pool.send_rpc(
                    user_id=owner_id,
                    req_id=f"clear-exec-{sk}",
                    method="sessions.patch",
                    params={"sessionKey": sk, "execNode": None, "execHost": None},
                    ip=ip,
                    token=container["gateway_token"],
                )
            except Exception:
                logger.debug("Failed to clear execNode on session %s (container may be down)", sk)

    # Reference-counted config patching: disable node tools on last disconnect
    count = _node_count.get(owner_id, 1)
    new_count = max(0, count - 1)
    _node_count[owner_id] = new_count
    if new_count == 0:
        try:
            await patch_openclaw_config(owner_id, {"tools": {"deny": ["canvas", "nodes"]}})
        except Exception:
            logger.debug("Failed to re-disable node tools for %s (container may be down)", owner_id)
        _node_count.pop(owner_id, None)

    # Per-user broadcast
    pool = get_gateway_pool()
    await pool.broadcast_to_member(
        owner_id, user_id,
        {"type": "node_status", "status": "disconnected"},
    )

    logger.info("Node proxy closed: user=%s conn=%s", user_id, connection_id)


def is_node_connection(connection_id: str) -> bool:
    """Check if a connection ID has a registered node upstream."""
    return connection_id in _node_upstreams
```

- [ ] **Step 5: Run tests**

Run: `cd apps/backend && CLERK_ISSUER=https://up-moth-55.clerk.accounts.dev uv run pytest tests/unit/routers/test_node_proxy.py -v --no-cov`
Expected: All 5 tests pass.

- [ ] **Step 6: Run all backend tests to verify no regressions**

Run: `cd apps/backend && CLERK_ISSUER=https://up-moth-55.clerk.accounts.dev uv run pytest tests/unit/ -q --no-cov`
Expected: All ~486+ tests pass.

- [ ] **Step 7: Commit**

```bash
git add apps/backend/routers/node_proxy.py apps/backend/core/gateway/node_connection.py apps/backend/tests/unit/routers/test_node_proxy.py
git commit -m "feat: per-user node tracking with ref-counted config patches and session cache"
```

---

### Task 3: Wire up `websocket_chat.py` — pass `user_id` to node handlers

**Files:**
- Modify: `apps/backend/routers/websocket_chat.py`

- [ ] **Step 1: Update the `role:"node"` connect handler to pass `user_id`**

At line 267 in `websocket_chat.py`, the current call is:

```python
hello = await handle_node_connect(
    owner_id=owner_id,
    connection_id=x_connection_id,
    connect_params=connect_params,
    management_api=management_api,
)
```

Change to:

```python
hello = await handle_node_connect(
    owner_id=owner_id,
    user_id=user_id,
    connection_id=x_connection_id,
    connect_params=connect_params,
    management_api=management_api,
)
```

- [ ] **Step 2: Update the `$disconnect` handler to pass `user_id`**

At line 171, the current code is:

```python
if is_node_connection(x_connection_id):
    await handle_node_disconnect(x_connection_id, owner_id)
```

The `$disconnect` handler (`ws_disconnect` function) needs `user_id`. It already looks up the connection from DynamoDB. Find where `user_id` is available and change to:

```python
if is_node_connection(x_connection_id):
    await handle_node_disconnect(x_connection_id, owner_id, user_id)
```

Verify that `user_id` is in scope in the `ws_disconnect` handler — it should be extracted from the DynamoDB connection record the same way as in `ws_message`.

- [ ] **Step 3: Run existing websocket_chat tests**

Run: `cd apps/backend && CLERK_ISSUER=https://up-moth-55.clerk.accounts.dev uv run pytest tests/unit/routers/test_websocket_agent_chat.py -q --no-cov`
Expected: All pass (the mock for `handle_node_connect` is patched in those tests).

- [ ] **Step 4: Commit**

```bash
git add apps/backend/routers/websocket_chat.py
git commit -m "feat: pass user_id to node connect/disconnect handlers"
```

---

### Task 4: Session patching — `execNode` integration

**Files:**
- Modify: `apps/backend/routers/websocket_chat.py` (the `_process_agent_chat_background` function)

- [ ] **Step 1: Add session patching before `chat.send`**

In `_process_agent_chat_background` (line 503), after the session_key is constructed (line 562) and before the `chat.send` RPC (line 572), add the `execNode` binding logic:

```python
# --- Node binding: pin this session to the user's Mac if connected ---
from routers.node_proxy import get_user_node, get_patched_session, set_patched_session

node_info = get_user_node(user_id)
if node_info:
    node_id = node_info["nodeId"]
    cached = get_patched_session(session_key)
    if cached != node_id:
        # Patch the session to bind exec to this user's node
        try:
            await pool.send_rpc(
                user_id=owner_id,
                req_id=f"bind-node-{session_key[:40]}",
                method="sessions.patch",
                params={
                    "sessionKey": session_key,
                    "execNode": node_id,
                    "execHost": "node",
                },
                ip=ip,
                token=container["gateway_token"],
            )
            set_patched_session(session_key, node_id)
            logger.info("Bound session %s to node %s", session_key, node_id[:16])
        except Exception:
            logger.warning("Failed to bind session %s to node", session_key)
```

Place this block between line 570 (after `container` and `ip` are resolved) and line 572 (before `chat.send`).

- [ ] **Step 2: Run all backend tests**

Run: `cd apps/backend && CLERK_ISSUER=https://up-moth-55.clerk.accounts.dev uv run pytest tests/unit/ -q --no-cov`
Expected: All pass.

- [ ] **Step 3: Commit**

```bash
git add apps/backend/routers/websocket_chat.py
git commit -m "feat: bind exec sessions to per-user nodes via sessions.patch"
```

---

### Task 5: Desktop app — clean up and accept user info

**Files:**
- Modify: `.worktrees/feat-desktop-app/apps/desktop/src-tauri/src/lib.rs`
- Modify: `.worktrees/feat-desktop-app/apps/desktop/src-tauri/src/node_client.rs`
- Delete: `.worktrees/feat-desktop-app/apps/desktop/src-tauri/src/node_proxy.rs`

- [ ] **Step 1: Delete `node_proxy.rs`**

```bash
cd .worktrees/feat-desktop-app
rm apps/desktop/src-tauri/src/node_proxy.rs
```

- [ ] **Step 2: Update `lib.rs`**

The current committed `lib.rs` references `mod node_proxy`, uses `ProxyHandle`, and spawns a loopback proxy. Replace it with the cleaned-up version that:
- Removes `mod node_proxy`
- Removes `proxy_handle` from `NodeState`
- Changes `send_auth_token` to accept `display_name` and `user_id`
- Adds a `log()` function for file-based logging
- Connects directly to the gateway (no proxy)

Key changes to `send_auth_token` (line 22):

```rust
#[tauri::command]
fn send_auth_token(
    token: String,
    display_name: String,
    user_id: String,
    state: State<'_, AuthState>,
    app: tauri::AppHandle,
) -> Result<(), String> {
```

Key changes to `start_node_host` (line 56):

```rust
async fn start_node_host(
    app: &tauri::AppHandle,
    ws_url: &str,
    clerk_jwt: &str,
    display_name: &str,
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    // ...
    let gateway_url = format!("{}?token={}", ws_url, clerk_jwt);
    log(&format!("[node] Connecting to {}", ws_url));
    let mut client = node_client::NodeClient::new(&gateway_url, display_name);
    // ...
}
```

- [ ] **Step 3: Fix `client.id` in `node_client.rs`**

At line 252 in `node_client.rs`, change:

```rust
"id": "isol8-desktop",
```

to:

```rust
"id": "node-host",
```

This matches the `GATEWAY_CLIENT_IDS.NODE_HOST` constant in OpenClaw's protocol.

- [ ] **Step 4: Build the desktop app**

```bash
cd apps/desktop/src-tauri && cargo build 2>&1 | grep -E "error|Finished"
```

Expected: `Finished dev profile` with no errors.

- [ ] **Step 5: Commit on the `feat/desktop-app` branch**

```bash
cd .worktrees/feat-desktop-app
git add -A apps/desktop/src-tauri/
git commit -m "feat: accept user info in send_auth_token, remove proxy, fix client.id"
```

---

### Task 6: Frontend — pass user info in Tauri IPC

**Files:**
- Modify: `apps/frontend/src/hooks/useGateway.tsx`

- [ ] **Step 1: Import `useUser` and pass user info**

At line 14 in `useGateway.tsx`, change:

```typescript
import { useAuth } from "@clerk/nextjs";
```

to:

```typescript
import { useAuth, useUser } from "@clerk/nextjs";
```

At line 97 (inside `GatewayProvider`), add alongside the existing `useAuth` call:

```typescript
const { user } = useUser();
```

At lines 227-232, change:

```typescript
if (typeof window !== "undefined" && token) {
    const tauri =
    (window as any).__TAURI__;
    if (tauri?.core?.invoke) {
        tauri.core.invoke("send_auth_token", { token }).catch(() => {});
    }
}
```

to:

```typescript
if (typeof window !== "undefined" && token) {
    const tauri =
    (window as any).__TAURI__;
    if (tauri?.core?.invoke) {
        tauri.core.invoke("send_auth_token", {
            token,
            displayName: user?.fullName || user?.firstName || "User",
            userId: user?.id || "",
        }).catch(() => {});
    }
}
```

- [ ] **Step 2: Lint**

Run: `cd apps/frontend && pnpm run lint`
Expected: 0 errors (existing warnings are fine).

- [ ] **Step 3: Commit**

```bash
git add apps/frontend/src/hooks/useGateway.tsx
git commit -m "feat: pass user display name and ID to desktop app via Tauri IPC"
```

---

### Task 7: Verification

- [ ] **Step 1: Run full backend test suite**

```bash
cd apps/backend && CLERK_ISSUER=https://up-moth-55.clerk.accounts.dev uv run pytest tests/unit/ -q --no-cov
```

Expected: All tests pass (486+ existing + 5 new node_proxy tests).

- [ ] **Step 2: Build desktop app `.app` bundle**

```bash
cd .worktrees/feat-desktop-app/apps/desktop/src-tauri
rm -rf target/debug/bundle
cargo tauri build --debug 2>&1 | tail -5
# If codesign fails with resource fork error:
xattr -cr target/debug/bundle/macos/Isol8.app
codesign --force --deep --sign "Developer ID Application: Prasiddha Parthsarthy (WZX4U3C22Y)" --entitlements entitlements.plist target/debug/bundle/macos/Isol8.app
```

- [ ] **Step 3: Push backend + frontend changes to main**

```bash
git push origin main
```

Wait for deploy to dev (watch `gh run watch <id> --repo Isol8AI/isol8 --exit-status`).

- [ ] **Step 4: Provision a fresh container and test**

Reprovision (DELETE + POST via debug endpoint or browser console). Then:

1. **Personal account test**: Open desktop app → sign in → send "run whoami" → should return Mac username
2. **Org account test**: Switch to org context → sign in → send "run whoami" → should return Mac username
3. **Verify `node_status` is per-user**: In an org, only the connecting member should see "Local tools available"

- [ ] **Step 5: Final commit — update spec status**

```bash
# Update the spec from Draft to Implemented
sed -i '' 's/Status: Draft/Status: Implemented/' docs/superpowers/specs/2026-04-12-desktop-per-user-node-design.md
git add docs/superpowers/specs/2026-04-12-desktop-per-user-node-design.md
git commit -m "docs: mark desktop per-user node spec as implemented"
```
