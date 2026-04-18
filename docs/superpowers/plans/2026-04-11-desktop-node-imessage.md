# Desktop App, Node Infrastructure & iMessage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the Isol8 Tauri desktop app with local tool execution (node), per-user session routing, and iMessage via BlueBubbles sidecar — all on a single feature branch tested end-to-end before merging to main.

**Architecture:** The Tauri desktop app connects to the user's OpenClaw container as a `role:"node"` WebSocket client. The backend patches sessions to route tool execution to the Mac. For iMessage, the desktop app manages a BlueBubbles sidecar process, and a reverse HTTP proxy through the node WebSocket bridges the Fargate container's BB channel plugin to the local BB instance.

**Tech Stack:** Tauri 2 (Rust), FastAPI (Python), Next.js 16 (React 19/TypeScript), OpenClaw node protocol, BlueBubbles REST API, tokio-tungstenite, reqwest

**Spec:** `docs/superpowers/specs/2026-04-11-imessage-bluebubbles-channel-design.md`

---

## File Map

### New Files

| File | Responsibility |
|------|----------------|
| `apps/backend/routers/bluebubbles_proxy.py` | HTTP proxy: container REST calls → node invoke → Mac → BB API |
| `apps/desktop/src-tauri/src/bluebubbles.rs` | BB sidecar lifecycle: download, spawn, health, configure, crash recovery |

### Modified Files (Backend)

| File | Change |
|------|--------|
| `apps/backend/routers/channels.py` | Add `"bluebubbles"` to `SUPPORTED_PROVIDERS`. Add webhook relay endpoint. |
| `apps/backend/routers/node_proxy.py` | Handle `"bluebubbles"` cap: patch/unpatch BB channel config on connect/disconnect. Store BB password. |
| `apps/backend/core/containers/config.py` | Add `bluebubbles` channel block (disabled by default) to `write_openclaw_config()` |
| `apps/backend/main.py` | Register `bluebubbles_proxy.router` |

### Modified Files (Tauri/Rust)

| File | Change |
|------|--------|
| `apps/desktop/src-tauri/src/node_invoke.rs` | Add `http.proxy` command handler |
| `apps/desktop/src-tauri/src/node_client.rs` | Dynamic caps (add/remove `"bluebubbles"`), send BB password in connect |
| `apps/desktop/src-tauri/src/lib.rs` | Register BB IPC commands, wire BB lifecycle to app start/quit |
| `apps/desktop/src-tauri/src/tray.rs` | Add iMessage status line |
| `apps/desktop/src-tauri/Cargo.toml` | Add `reqwest` dependency |

### Modified Files (Frontend)

| File | Change |
|------|--------|
| `apps/frontend/src/lib/channels.ts` | Add `"bluebubbles"` to Provider type, PROVIDERS, PROVIDER_LABELS |
| `apps/frontend/src/components/control/panels/channels-types.ts` | Add `bluebubbles` to CHANNEL_CONFIG_FIELDS |
| `apps/frontend/src/components/channels/BotSetupWizard.tsx` | Add iMessage wizard steps (desktop auto + manual fallback) |

### Test Files

| File | Purpose |
|------|---------|
| `apps/backend/tests/unit/routers/test_bluebubbles_proxy.py` | Tests for HTTP proxy endpoint |
| `apps/backend/tests/unit/routers/test_node_proxy.py` | Extend existing tests for BB caps handling |

---

## Task 1: Branch Consolidation

**Goal:** Create a single feature branch combining per-user-node backend + feat/desktop-app Tauri code.

**Important:** Nothing touches main. We create a new branch, cherry-pick from both sources, resolve conflicts.

- [ ] **Step 1: Create feature branch off main**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync
git checkout main
git pull origin main
git checkout -b feat/desktop-imessage
```

- [ ] **Step 2: Cherry-pick per-user-node commits**

The per-user-node branch has 4 commits on top of main. Get their SHAs:

```bash
git log main..worktree-per-user-node --oneline
```

Cherry-pick them in order (oldest first):

```bash
git cherry-pick <sha1> <sha2> <sha3> <sha4>
```

If any conflict, resolve by keeping the per-user-node version (it's the superset).

- [ ] **Step 3: Cherry-pick desktop-app-exclusive commits**

The feat/desktop-app branch has many commits, but most are already on main via merged PRs. We need only the desktop-exclusive ones (Tauri code, desktop_auth, frontend auth components). List the unique commits:

```bash
git log main..feat/desktop-app --oneline -- apps/desktop/ .github/workflows/desktop-build.yml apps/backend/routers/desktop_auth.py "apps/frontend/src/components/auth/" "apps/frontend/src/hooks/useDesktopAuth.ts" "apps/frontend/src/app/auth/desktop-callback/" "apps/frontend/src/types/electron.d.ts"
```

Cherry-pick these commits. For commits that also touch `node_proxy.py`, `websocket_chat.py`, or `connection_pool.py`, the per-user-node version already has the correct content — resolve conflicts by keeping the current (per-user-node) version of those files while accepting the desktop-exclusive changes.

- [ ] **Step 4: Manual merge useGateway.tsx**

The per-user-node branch's `useGateway.tsx` has `userId`/`displayName` passing. The feat/desktop-app branch has `nodeConnected` state and `node_status` handling. Both are needed.

Read the current file (which has per-user-node's changes), then add the missing pieces from feat/desktop-app:

1. Add `nodeConnected` state variable
2. Add `node_status` message handler that updates `nodeConnected`
3. Add `onNodeStatus` callback in the context value

Check the feat/desktop-app worktree's version for the exact code:

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/.worktrees/feat-desktop-app
grep -n "nodeConnected\|node_status\|onNodeStatus" apps/frontend/src/hooks/useGateway.tsx
```

Integrate those additions into the current file.

- [ ] **Step 5: Verify no regressions**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync
cd apps/backend && uv run pytest tests/ -v --tb=short
cd ../frontend && pnpm run lint && pnpm run build
```

- [ ] **Step 6: Commit the merge resolution**

```bash
git add -A
git commit -m "feat: consolidate desktop-app + per-user-node branches

Combines Tauri desktop app (node_client, exec_approvals, tray, CI)
with per-user node routing (ref-counted config, session binding, broadcast_to_member).

Conflict resolution: per-user-node backend wins on node_proxy.py,
websocket_chat.py; useGateway.tsx manually merged (node status + identity)."
```

---

## Task 2: Fix Path Discrepancy

**Files:**
- Check: `apps/backend/core/gateway/node_connection.py`
- Check: EFS provisioning code in `apps/backend/core/containers/config.py` and `apps/backend/core/containers/ecs_manager.py`

The device identity spec says `nodes/.node-device-key.pem` but the implementation uses `devices/.node-device-key.pem`. We need to verify which path the container's OpenClaw actually expects.

- [ ] **Step 1: Check what paths the backend writes during provisioning**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync
grep -rn "node-device-key\|paired.json\|devices/\|nodes/" apps/backend/core/containers/ apps/backend/core/gateway/node_connection.py
```

- [ ] **Step 2: Check what path the container expects**

The container reads `paired.json` to validate device identity. Check which directory OpenClaw looks in by searching for any documentation or config:

```bash
grep -rn "paired.json\|NODE_KEY_PATH\|DEVICE_KEY" apps/backend/
```

- [ ] **Step 3: Align paths**

If the implementation uses `devices/` and it works (hello-ok succeeds), keep `devices/` and update the design spec. If the container expects `nodes/`, update the code constants.

Make the change and commit:

```bash
git add -A
git commit -m "fix: align device key path between spec and implementation"
```

---

## Task 3: Backend BlueBubbles HTTP Proxy

**Files:**
- Create: `apps/backend/routers/bluebubbles_proxy.py`
- Create: `apps/backend/tests/unit/routers/test_bluebubbles_proxy.py`
- Modify: `apps/backend/main.py` (register router)

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/unit/routers/test_bluebubbles_proxy.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.bluebubbles_proxy import router, _bb_passwords

app = FastAPI()
app.include_router(router, prefix="/api/v1/proxy/bluebubbles")


@pytest.fixture(autouse=True)
def reset_state():
    _bb_passwords.clear()
    yield
    _bb_passwords.clear()


def test_proxy_returns_503_when_no_node():
    """Proxy returns 503 when no desktop node is connected."""
    client = TestClient(app)
    _bb_passwords["owner_123"] = "secret"
    resp = client.get(
        "/api/v1/proxy/bluebubbles/owner_123/api/v1/chats",
        headers={"Authorization": "Bearer secret"},
    )
    assert resp.status_code == 503
    assert resp.json()["error"] == "imessage_unavailable"


def test_proxy_returns_401_with_wrong_password():
    """Proxy rejects requests with wrong BB password."""
    client = TestClient(app)
    _bb_passwords["owner_123"] = "correct"
    resp = client.get(
        "/api/v1/proxy/bluebubbles/owner_123/api/v1/chats",
        headers={"Authorization": "Bearer wrong"},
    )
    assert resp.status_code == 401


def test_proxy_returns_401_with_no_auth():
    """Proxy rejects requests with no auth header."""
    client = TestClient(app)
    resp = client.get("/api/v1/proxy/bluebubbles/owner_123/api/v1/chats")
    assert resp.status_code == 401


def test_proxy_returns_404_for_unknown_owner():
    """Proxy returns 404 when owner has no BB password registered."""
    client = TestClient(app)
    resp = client.get(
        "/api/v1/proxy/bluebubbles/unknown/api/v1/chats",
        headers={"Authorization": "Bearer secret"},
    )
    assert resp.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd apps/backend && uv run pytest tests/unit/routers/test_bluebubbles_proxy.py -v
```

Expected: ImportError (module doesn't exist yet)

- [ ] **Step 3: Implement the proxy endpoint**

```python
# apps/backend/routers/bluebubbles_proxy.py
"""
Reverse HTTP proxy: container's BB plugin -> backend -> node invoke -> Mac -> BB REST API.

The container's openclaw.json has serverUrl pointing here. Requests are
tunneled through the node WebSocket to the Tauri desktop app, which
forwards to the local BlueBubbles server at localhost:1234.
"""
import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException, Request, Response

router = APIRouter()
logger = logging.getLogger(__name__)

# owner_id -> BB password (set by node_proxy on connect, cleared on disconnect)
_bb_passwords: dict[str, str] = {}


def set_bb_password(owner_id: str, password: str) -> None:
    _bb_passwords[owner_id] = password


def clear_bb_password(owner_id: str) -> None:
    _bb_passwords.pop(owner_id, None)


def get_bb_password(owner_id: str) -> str | None:
    return _bb_passwords.get(owner_id)


def _validate_bb_auth(owner_id: str, request: Request) -> None:
    """Validate BB password from Authorization: Bearer header."""
    stored = _bb_passwords.get(owner_id)
    if not stored:
        raise HTTPException(status_code=401, detail="No BlueBubbles password registered")
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization")
    token = auth[7:]
    if token != stored:
        raise HTTPException(status_code=401, detail="Invalid BlueBubbles password")


@router.api_route(
    "/{owner_id}/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
)
async def proxy_to_bluebubbles(owner_id: str, path: str, request: Request) -> Response:
    """Proxy any HTTP request to the user's BlueBubbles via node invoke."""
    _validate_bb_auth(owner_id, request)

    # Look up the connected node for this owner via node_proxy's state.
    # _node_upstreams maps connection_id -> upstream, but we need to find
    # the upstream by owner_id. Use the _user_nodes dict to find the
    # connection_id, then look up the upstream.
    from routers.node_proxy import _node_upstreams, _user_nodes

    # Find any user's node for this owner (BB is per-container, not per-user)
    upstream = None
    for user_id, info in _user_nodes.items():
        if info.get("owner_id") == owner_id:
            conn_id = info.get("connection_id")
            upstream = _node_upstreams.get(conn_id)
            if upstream:
                break

    if not upstream:
        raise HTTPException(
            status_code=503,
            detail={"error": "imessage_unavailable", "detail": "Desktop app not connected"},
        )

    body = await request.body()
    query = str(request.query_params) if request.query_params else ""

    # Build the invoke request
    invoke_params = {
        "method": request.method,
        "path": f"/{path}",
        "query": query,
        "headers": dict(request.headers),
        "body": body.decode("utf-8") if body else None,
    }

    try:
        result = await upstream.send_invoke(
            command="http.proxy",
            params=invoke_params,
            timeout=30.0,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="BlueBubbles request timed out")
    except Exception as e:
        logger.error(f"BB proxy invoke failed for {owner_id}: {e}")
        raise HTTPException(status_code=502, detail="BlueBubbles proxy error")

    if not result.get("ok"):
        raise HTTPException(
            status_code=502,
            detail=result.get("error", "BlueBubbles proxy error"),
        )

    payload = result.get("payload", {})
    return Response(
        content=payload.get("body", ""),
        status_code=payload.get("status", 200),
        headers=payload.get("headers", {}),
        media_type=payload.get("headers", {}).get("content-type", "application/json"),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd apps/backend && uv run pytest tests/unit/routers/test_bluebubbles_proxy.py -v
```

Expected: 4 tests PASS (the proxy logic tests that don't require a live node connection)

- [ ] **Step 5: Register router in main.py**

Add to `apps/backend/main.py` after the existing router registrations (after line 237):

```python
from routers import bluebubbles_proxy
# ... in the router registration block:
app.include_router(bluebubbles_proxy.router, prefix="/api/v1/proxy/bluebubbles")
```

- [ ] **Step 6: Commit**

```bash
git add apps/backend/routers/bluebubbles_proxy.py apps/backend/tests/unit/routers/test_bluebubbles_proxy.py apps/backend/main.py
git commit -m "feat(backend): add BlueBubbles HTTP proxy endpoint

Reverse proxy for container BB plugin REST calls. Routes through
node invoke to the Tauri desktop app's local BB instance.
Auth via shared BB password in Authorization: Bearer header."
```

---

## Task 4: Backend BlueBubbles Webhook Relay

**Files:**
- Modify: `apps/backend/routers/channels.py`

- [ ] **Step 1: Add "bluebubbles" to SUPPORTED_PROVIDERS**

In `apps/backend/routers/channels.py` line 32, change:

```python
SUPPORTED_PROVIDERS = {"telegram", "discord", "slack"}
```

to:

```python
SUPPORTED_PROVIDERS = {"telegram", "discord", "slack", "bluebubbles"}
```

- [ ] **Step 2: Add webhook relay endpoint**

Add this endpoint to `apps/backend/routers/channels.py` after the existing endpoints (after the last endpoint, around line 278):

```python
@router.post("/bluebubbles/webhook/{owner_id}")
async def bluebubbles_webhook_relay(owner_id: str, request: Request):
    """
    Relay BlueBubbles webhooks from the user's Mac to their container.

    BlueBubbles on the Mac POSTs here when a new iMessage arrives.
    We validate the BB password and forward to the container's
    /bluebubbles-webhook endpoint internally via Cloud Map.
    """
    import httpx

    password = request.query_params.get("password")
    if not password:
        raise HTTPException(status_code=401, detail="Missing password")

    # Validate against stored BB password
    from routers.bluebubbles_proxy import get_bb_password
    stored = get_bb_password(owner_id)
    if not stored or password != stored:
        raise HTTPException(status_code=401, detail="Invalid password")

    # Discover container IP via Cloud Map
    from core.containers import get_ecs_manager
    ecs = get_ecs_manager()
    container_ip = await ecs.discover_service(owner_id)
    if not container_ip:
        raise HTTPException(status_code=503, detail="Container not found")

    # Forward webhook to container
    body = await request.body()
    container_url = f"http://{container_ip}:3000/bluebubbles-webhook?password={password}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                container_url,
                content=body,
                headers={"content-type": request.headers.get("content-type", "application/json")},
            )
        return Response(content=resp.content, status_code=resp.status_code)
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Container webhook timeout")
    except Exception as e:
        logger.error(f"BB webhook relay failed for {owner_id}: {e}")
        raise HTTPException(status_code=502, detail="Webhook relay failed")
```

Add the missing imports at the top of the file:

```python
from fastapi import Request, Response
```

- [ ] **Step 3: Run existing channel tests + lint**

```bash
cd apps/backend && uv run pytest tests/ -v --tb=short -k "channel"
cd apps/backend && uv run ruff check routers/channels.py
```

- [ ] **Step 4: Commit**

```bash
git add apps/backend/routers/channels.py
git commit -m "feat(backend): add BlueBubbles webhook relay + provider

Adds bluebubbles to SUPPORTED_PROVIDERS and a webhook relay endpoint
that forwards BB webhooks from the user's Mac to their container
via Cloud Map discovery."
```

---

## Task 5: Backend BB Caps Handling in node_proxy

**Files:**
- Modify: `apps/backend/routers/node_proxy.py`
- Modify: `apps/backend/tests/unit/routers/test_node_proxy.py`

- [ ] **Step 1: Write failing test for BB caps**

Add to `apps/backend/tests/unit/routers/test_node_proxy.py`:

```python
@pytest.mark.asyncio
async def test_connect_with_bb_caps_patches_channel_config(mock_pool, mock_upstream):
    """When node connects with bluebubbles cap, BB channel config is patched."""
    with patch("routers.node_proxy.patch_openclaw_config") as mock_patch:
        mock_patch.return_value = None
        await handle_node_connect(
            owner_id="owner_1",
            user_id="user_1",
            connection_id="conn_bb",
            body={"caps": ["system", "bluebubbles"], "bb_password": "secret123"},
            pool=mock_pool,
            display_name="Test",
        )

    # Should have two patches: one for tools.deny, one for BB channel
    calls = mock_patch.call_args_list
    bb_call = [c for c in calls if "bluebubbles" in str(c)]
    assert len(bb_call) >= 1, "Expected a patch call enabling bluebubbles channel"


@pytest.mark.asyncio
async def test_disconnect_with_bb_disables_channel(mock_pool, mock_upstream):
    """When last BB-capable node disconnects, BB channel is disabled."""
    with patch("routers.node_proxy.patch_openclaw_config") as mock_patch:
        mock_patch.return_value = None
        # Connect first
        await handle_node_connect(
            owner_id="owner_1", user_id="user_1", connection_id="conn_bb",
            body={"caps": ["system", "bluebubbles"], "bb_password": "secret123"},
            pool=mock_pool, display_name="Test",
        )
        # Disconnect
        await handle_node_disconnect("conn_bb", mock_pool)

    # Last call should disable BB channel
    last_call = mock_patch.call_args_list[-1]
    assert "bluebubbles" in str(last_call)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd apps/backend && uv run pytest tests/unit/routers/test_node_proxy.py -v -k "bb"
```

Expected: FAIL (handle_node_connect doesn't accept `bb_password` or handle `bluebubbles` cap yet)

- [ ] **Step 3: Extend handle_node_connect for BB caps**

In `apps/backend/routers/node_proxy.py`, modify `handle_node_connect()` to:

1. Accept `bb_password` from the connect body
2. Check if `"bluebubbles"` is in `caps`
3. If yes, store the password and patch `openclaw.json` with BB channel config

Add after the existing config patch block (after the `_node_count` 0→1 transition patch, around line 119):

```python
    # BlueBubbles channel config
    caps = body.get("caps", [])
    if "bluebubbles" in caps:
        bb_password = body.get("bb_password", "")
        if bb_password:
            from routers.bluebubbles_proxy import set_bb_password
            set_bb_password(owner_id, bb_password)

            from core.config import settings
            api_base = settings.API_BASE_URL or "https://api.isol8.co"
            await patch_openclaw_config(owner_id, {
                "channels": {
                    "bluebubbles": {
                        "enabled": True,
                        "serverUrl": f"{api_base}/api/v1/proxy/bluebubbles/{owner_id}",
                        "password": bb_password,
                        "webhookPath": "/bluebubbles-webhook",
                        "dmPolicy": "pairing",
                    }
                }
            })
            logger.info(f"BlueBubbles channel enabled for {owner_id}")
```

In `handle_node_disconnect()`, add BB cleanup before the existing config patch (around line 170):

```python
    # Disable BlueBubbles if this was the BB-capable node
    if node_info:
        owner_id = node_info.get("owner_id")
        from routers.bluebubbles_proxy import clear_bb_password
        clear_bb_password(owner_id)
        try:
            await patch_openclaw_config(owner_id, {
                "channels": {
                    "bluebubbles": {
                        "enabled": False,
                    }
                }
            })
            logger.info(f"BlueBubbles channel disabled for {owner_id}")
        except Exception as e:
            logger.warning(f"Failed to disable BB channel for {owner_id}: {e}")
```

- [ ] **Step 4: Run tests**

```bash
cd apps/backend && uv run pytest tests/unit/routers/test_node_proxy.py -v
```

Expected: All tests PASS (existing + new BB tests)

- [ ] **Step 5: Commit**

```bash
git add apps/backend/routers/node_proxy.py apps/backend/tests/unit/routers/test_node_proxy.py
git commit -m "feat(backend): handle bluebubbles cap in node connect/disconnect

When a node connects with bluebubbles capability, patches openclaw.json
to enable the BB channel with proxy serverUrl. On disconnect, disables
the channel and clears the stored BB password."
```

---

## Task 6: Backend BB Config Generation

**Files:**
- Modify: `apps/backend/core/containers/config.py`

- [ ] **Step 1: Add bluebubbles to initial config**

In `apps/backend/core/containers/config.py`, add the bluebubbles channel to the channels block (after line 451, after the slack entry):

```python
"bluebubbles": {"enabled": False, "dmPolicy": "pairing"},
```

This ships disabled by default. The desktop app's node connection dynamically enables it when BB is running.

- [ ] **Step 2: Run backend tests**

```bash
cd apps/backend && uv run pytest tests/ -v --tb=short
```

- [ ] **Step 3: Commit**

```bash
git add apps/backend/core/containers/config.py
git commit -m "feat(backend): add bluebubbles channel to initial container config

Ships disabled by default. Enabled dynamically when desktop app
connects with BlueBubbles capability."
```

---

## Task 7: Rust http.proxy Invoke Handler

**Files:**
- Modify: `apps/desktop/src-tauri/src/node_invoke.rs`
- Modify: `apps/desktop/src-tauri/Cargo.toml`

- [ ] **Step 1: Add reqwest dependency**

In `apps/desktop/src-tauri/Cargo.toml`, add to `[dependencies]`:

```toml
reqwest = { version = "0.12", features = ["json"] }
dirs = "6"
```

Note: `lazy_static` and `uuid` are already in the existing `Cargo.toml` from `feat/desktop-app`.

- [ ] **Step 2: Add http.proxy handler to dispatch**

In `apps/desktop/src-tauri/src/node_invoke.rs`, add the new command to the dispatch match (line 38):

```rust
"http.proxy" => handle_http_proxy(&request).await,
```

- [ ] **Step 3: Implement http.proxy handler**

Add this function to `apps/desktop/src-tauri/src/node_invoke.rs` (after the existing handlers, around line 255):

```rust
async fn handle_http_proxy(request: &NodeInvokeRequest) -> Result<NodeInvokeResult, Box<dyn std::error::Error + Send + Sync>> {
    let params = parse_params(&request.params_json)?;
    let method = params.get("method").and_then(|v| v.as_str()).unwrap_or("GET");
    let path = params.get("path").and_then(|v| v.as_str()).unwrap_or("/");
    let query = params.get("query").and_then(|v| v.as_str()).unwrap_or("");
    let body = params.get("body").and_then(|v| v.as_str());

    let mut url = format!("http://localhost:1234{path}");
    if !query.is_empty() {
        url.push('?');
        url.push_str(query);
    }

    let client = reqwest::Client::new();
    let mut req_builder = match method.to_uppercase().as_str() {
        "GET" => client.get(&url),
        "POST" => client.post(&url),
        "PUT" => client.put(&url),
        "DELETE" => client.delete(&url),
        "PATCH" => client.patch(&url),
        "HEAD" => client.head(&url),
        _ => client.get(&url),
    };

    // Forward headers (skip hop-by-hop headers)
    if let Some(headers) = params.get("headers").and_then(|v| v.as_object()) {
        for (key, val) in headers {
            let k = key.to_lowercase();
            if k == "host" || k == "connection" || k == "transfer-encoding" {
                continue;
            }
            if let Some(v) = val.as_str() {
                if let Ok(name) = reqwest::header::HeaderName::from_bytes(key.as_bytes()) {
                    if let Ok(value) = reqwest::header::HeaderValue::from_str(v) {
                        req_builder = req_builder.header(name, value);
                    }
                }
            }
        }
    }

    if let Some(b) = body {
        req_builder = req_builder.body(b.to_string());
    }

    let resp = req_builder
        .timeout(std::time::Duration::from_secs(25))
        .send()
        .await?;

    let status = resp.status().as_u16();
    let resp_headers: serde_json::Map<String, serde_json::Value> = resp
        .headers()
        .iter()
        .map(|(k, v)| (k.to_string(), serde_json::Value::String(v.to_str().unwrap_or("").to_string())))
        .collect();
    let resp_body = resp.text().await.unwrap_or_default();

    Ok(NodeInvokeResult {
        ok: true,
        payload_json: serde_json::to_string(&serde_json::json!({
            "status": status,
            "headers": resp_headers,
            "body": resp_body,
        }))?,
        error: None,
    })
}
```

- [ ] **Step 4: Build to verify compilation**

```bash
cd apps/desktop && cargo build 2>&1 | head -20
```

Expected: Build succeeds

- [ ] **Step 5: Commit**

```bash
git add apps/desktop/src-tauri/src/node_invoke.rs apps/desktop/src-tauri/Cargo.toml
git commit -m "feat(desktop): add http.proxy invoke handler

Proxies HTTP requests from the container's BB plugin to the local
BlueBubbles server at localhost:1234. Forwards method, path, query,
headers, and body. Returns status, headers, and body."
```

---

## Task 8: Rust BlueBubbles Sidecar Manager

**Files:**
- Create: `apps/desktop/src-tauri/src/bluebubbles.rs`

- [ ] **Step 1: Create the sidecar manager module**

```rust
// apps/desktop/src-tauri/src/bluebubbles.rs

use std::path::PathBuf;
use std::process::Stdio;
use std::sync::Mutex;
use tokio::process::{Child, Command};

lazy_static::lazy_static! {
    static ref BB_STATE: Mutex<BbState> = Mutex::new(BbState::default());
}

#[derive(Default)]
struct BbState {
    process: Option<u32>,  // PID
    password: Option<String>,
    enabled: bool,
    status: String,
    restart_count: u32,
}

const BB_PORT: u16 = 1234;
const BB_HEALTH_URL: &str = "http://localhost:1234/api/v1/server/info";
const MAX_RESTARTS: u32 = 3;

fn bb_app_dir() -> PathBuf {
    let mut dir = dirs::data_dir().unwrap_or_else(|| PathBuf::from("/tmp"));
    dir.push("co.isol8.desktop");
    dir.push("BlueBubbles");
    dir
}

fn bb_app_path() -> PathBuf {
    bb_app_dir().join("BlueBubbles.app").join("Contents").join("MacOS").join("BlueBubbles")
}

pub fn get_status() -> String {
    BB_STATE.lock().unwrap().status.clone()
}

pub fn get_password() -> Option<String> {
    BB_STATE.lock().unwrap().password.clone()
}

fn set_status(status: &str) {
    BB_STATE.lock().unwrap().status = status.to_string();
}

pub async fn enable(owner_id: &str, webhook_base_url: &str) -> Result<String, String> {
    // Generate password if first time
    let password = {
        let mut state = BB_STATE.lock().unwrap();
        if state.password.is_none() {
            state.password = Some(uuid::Uuid::new_v4().to_string().replace("-", ""));
        }
        state.enabled = true;
        state.restart_count = 0;
        state.password.clone().unwrap()
    };

    set_status("starting");

    // Check if BB app is installed
    if !bb_app_path().exists() {
        set_status("downloading");
        download().await.map_err(|e| format!("Download failed: {e}"))?;
    }

    // Start BB
    start_process().await.map_err(|e| format!("Start failed: {e}"))?;

    // Wait for health
    wait_for_healthy(30).await.map_err(|e| format!("Health check failed: {e}"))?;

    // Configure BB
    let webhook_url = format!("{webhook_base_url}/api/v1/channels/bluebubbles/webhook/{owner_id}?password={password}");
    configure(&password, &webhook_url).await.map_err(|e| format!("Configure failed: {e}"))?;

    // Persist password to disk so BB can auto-start on next app launch
    persist_password(&password);

    // Spawn crash recovery watcher
    tokio::spawn(watch_and_restart());

    set_status("connected");
    Ok(password)
}

pub async fn disable() -> Result<(), String> {
    {
        let mut state = BB_STATE.lock().unwrap();
        state.enabled = false;
    }
    stop_process().await;
    set_status("disconnected");
    Ok(())
}

async fn download() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let dir = bb_app_dir();
    std::fs::create_dir_all(&dir)?;

    // Download latest BlueBubbles release from GitHub
    let client = reqwest::Client::new();
    let releases_url = "https://api.github.com/repos/BlueBubblesApp/bluebubbles-server/releases/latest";
    let release: serde_json::Value = client
        .get(releases_url)
        .header("User-Agent", "isol8-desktop")
        .send()
        .await?
        .json()
        .await?;

    // Find the macOS .dmg or .zip asset
    let assets = release["assets"].as_array().ok_or("No assets in release")?;
    let mac_asset = assets.iter()
        .find(|a| {
            let name = a["name"].as_str().unwrap_or("");
            name.contains("mac") || name.contains("darwin") || name.ends_with(".dmg")
        })
        .ok_or("No macOS asset found")?;

    let download_url = mac_asset["browser_download_url"].as_str().ok_or("No download URL")?;
    let asset_name = mac_asset["name"].as_str().unwrap_or("bluebubbles.dmg");

    let asset_path = dir.join(asset_name);
    let bytes = client.get(download_url)
        .header("User-Agent", "isol8-desktop")
        .send()
        .await?
        .bytes()
        .await?;
    std::fs::write(&asset_path, &bytes)?;

    // If .dmg, mount and copy .app
    if asset_name.ends_with(".dmg") {
        let output = std::process::Command::new("hdiutil")
            .args(["attach", asset_path.to_str().unwrap(), "-nobrowse", "-quiet"])
            .output()?;
        if !output.status.success() {
            return Err(format!("hdiutil attach failed: {}", String::from_utf8_lossy(&output.stderr)).into());
        }

        // Copy .app from mounted volume
        let copy_output = std::process::Command::new("cp")
            .args(["-R", "/Volumes/BlueBubbles/BlueBubbles.app", dir.join("BlueBubbles.app").to_str().unwrap()])
            .output()?;

        // Detach
        let _ = std::process::Command::new("hdiutil")
            .args(["detach", "/Volumes/BlueBubbles", "-quiet"])
            .output();

        // Clean up .dmg
        let _ = std::fs::remove_file(&asset_path);

        if !copy_output.status.success() {
            return Err("Failed to copy BlueBubbles.app from DMG".into());
        }
    }

    Ok(())
}

async fn start_process() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let path = bb_app_path();
    if !path.exists() {
        return Err("BlueBubbles app not found".into());
    }

    let child = Command::new(&path)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()?;

    let pid = child.id().unwrap_or(0);
    BB_STATE.lock().unwrap().process = Some(pid);

    // Detach — we track by PID, not by Child handle
    tokio::spawn(async move {
        let _ = child.wait_with_output().await;
    });

    Ok(())
}

async fn stop_process() {
    let pid = BB_STATE.lock().unwrap().process.take();
    if let Some(pid) = pid {
        let _ = std::process::Command::new("kill")
            .arg(pid.to_string())
            .output();
    }
}

async fn wait_for_healthy(timeout_secs: u64) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let client = reqwest::Client::new();
    let deadline = tokio::time::Instant::now() + std::time::Duration::from_secs(timeout_secs);

    loop {
        if tokio::time::Instant::now() > deadline {
            return Err("BlueBubbles health check timed out".into());
        }
        match client.get(BB_HEALTH_URL).timeout(std::time::Duration::from_secs(2)).send().await {
            Ok(resp) if resp.status().is_success() => return Ok(()),
            _ => tokio::time::sleep(std::time::Duration::from_secs(1)).await,
        }
    }
}

async fn configure(password: &str, webhook_url: &str) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let client = reqwest::Client::new();
    let base = format!("http://localhost:{BB_PORT}");

    // Set password
    client.put(format!("{base}/api/v1/server/settings"))
        .json(&serde_json::json!({"password": password}))
        .send()
        .await?;

    // Set webhook URL
    client.post(format!("{base}/api/v1/server/webhooks"))
        .json(&serde_json::json!({"url": webhook_url, "events": ["new-message"]}))
        .send()
        .await?;

    Ok(())
}

/// Spawn a background task that watches the BB child process and restarts
/// on crash (up to MAX_RESTARTS with exponential backoff).
pub async fn watch_and_restart() {
    loop {
        let (enabled, pid) = {
            let state = BB_STATE.lock().unwrap();
            (state.enabled, state.process)
        };
        if !enabled {
            break;
        }

        // Check if process is still alive
        if let Some(pid) = pid {
            let alive = std::process::Command::new("kill")
                .args(["-0", &pid.to_string()])
                .output()
                .map(|o| o.status.success())
                .unwrap_or(false);

            if !alive {
                let restart_count = {
                    let mut state = BB_STATE.lock().unwrap();
                    state.restart_count += 1;
                    state.process = None;
                    state.restart_count
                };

                if restart_count <= MAX_RESTARTS {
                    set_status("restarting");
                    let delay = std::time::Duration::from_secs(1 << (restart_count - 1)); // 1s, 2s, 4s
                    tokio::time::sleep(delay).await;
                    if let Err(e) = start_process().await {
                        set_status(&format!("error: {e}"));
                        break;
                    }
                    if let Err(e) = wait_for_healthy(30).await {
                        set_status(&format!("error: {e}"));
                        break;
                    }
                    set_status("connected");
                } else {
                    set_status("error: max restarts exceeded");
                    break;
                }
            }
        }

        tokio::time::sleep(std::time::Duration::from_secs(5)).await;
    }
}

/// Check if BB was previously enabled (password exists in store).
/// Called on app startup to auto-restart BB.
pub fn was_previously_enabled() -> bool {
    // Check if the app data directory has a BB password file
    let pw_path = bb_app_dir().join(".bb-password");
    pw_path.exists()
}

/// Persist the BB password to disk (survives app restarts).
fn persist_password(password: &str) {
    let dir = bb_app_dir();
    let _ = std::fs::create_dir_all(&dir);
    let _ = std::fs::write(dir.join(".bb-password"), password);
}

/// Load persisted BB password from disk.
pub fn load_persisted_password() -> Option<String> {
    let path = bb_app_dir().join(".bb-password");
    std::fs::read_to_string(path).ok()
}
```

- [ ] **Step 2: Add mod declaration**

In `apps/desktop/src-tauri/src/lib.rs`, add at the top with the other `mod` declarations:

```rust
mod bluebubbles;
```

- [ ] **Step 3: Build to verify**

```bash
cd apps/desktop && cargo build 2>&1 | head -20
```

- [ ] **Step 4: Commit**

```bash
git add apps/desktop/src-tauri/src/bluebubbles.rs apps/desktop/src-tauri/src/lib.rs
git commit -m "feat(desktop): add BlueBubbles sidecar manager

Manages BB lifecycle: download from GitHub releases, spawn as child
process, health polling, auto-configure password + webhook URL,
crash recovery. Stores password for node caps handshake."
```

---

## Task 9: Rust Dynamic Caps + BB IPC Commands

**Files:**
- Modify: `apps/desktop/src-tauri/src/node_client.rs`
- Modify: `apps/desktop/src-tauri/src/lib.rs`

- [ ] **Step 1: Add dynamic caps to node_client.rs**

In `apps/desktop/src-tauri/src/node_client.rs`, modify the `NodeClient` struct to accept dynamic caps:

Add a field to `NodeClient`:
```rust
bb_enabled: bool,
```

Initialize it to `false` in `NodeClient::new()`.

Add a public method:
```rust
pub fn set_bb_enabled(&mut self, enabled: bool) {
    self.bb_enabled = enabled;
}
```

In the connect handshake (around line 253), change the static caps to dynamic:

```rust
let caps = if self.bb_enabled {
    serde_json::json!(["system", "bluebubbles"])
} else {
    serde_json::json!(["system"])
};
```

And use `caps` in the connect message instead of the hardcoded `["system"]`.

Also add `bb_password` to the connect params when BB is enabled:

```rust
if self.bb_enabled {
    if let Some(pw) = crate::bluebubbles::get_password() {
        params["bb_password"] = serde_json::Value::String(pw);
    }
}
```

- [ ] **Step 2: Add BB IPC commands to lib.rs**

In `apps/desktop/src-tauri/src/lib.rs`, add three new Tauri commands:

```rust
#[tauri::command]
async fn enable_bluebubbles(app: AppHandle, owner_id: String) -> Result<String, String> {
    let api_base = std::env::var("ISOL8_API_URL")
        .unwrap_or_else(|_| "https://api-dev.isol8.co".to_string());

    let password = bluebubbles::enable(&owner_id, &api_base).await?;

    // Update tray
    tray::update_tray_status(&app, &format!("Node: connected | iMessage: connected"));

    // Emit status event to frontend
    let _ = app.emit("bluebubbles_status", serde_json::json!({"status": "connected"}));

    Ok(password)
}

#[tauri::command]
async fn disable_bluebubbles(app: AppHandle) -> Result<(), String> {
    bluebubbles::disable().await?;
    tray::update_tray_status(&app, "Node: connected | iMessage: disconnected");
    let _ = app.emit("bluebubbles_status", serde_json::json!({"status": "disconnected"}));
    Ok(())
}

#[tauri::command]
fn bluebubbles_status() -> String {
    bluebubbles::get_status()
}
```

Register them in the invoke_handler (line 153):

```rust
.invoke_handler(tauri::generate_handler![
    send_auth_token,
    is_desktop,
    get_node_status,
    enable_bluebubbles,
    disable_bluebubbles,
    bluebubbles_status,
])
```

Add auto-start on app launch (in the `run()` function, after tray setup):

```rust
// Auto-start BlueBubbles if it was previously enabled
if bluebubbles::was_previously_enabled() {
    let app_handle = app.handle().clone();
    tokio::spawn(async move {
        if let Some(password) = bluebubbles::load_persisted_password() {
            // Restore the password in memory
            let owner_id = ""; // Will be set when node connects and frontend sends owner context
            let api_base = std::env::var("ISOL8_API_URL")
                .unwrap_or_else(|_| "https://api-dev.isol8.co".to_string());
            if let Err(e) = bluebubbles::enable(owner_id, &api_base).await {
                eprintln!("BB auto-start failed: {e}");
            }
        }
    });
}
```

Add graceful shutdown on app quit (in the Tauri builder, before `.run()`):

```rust
.on_window_event(|window, event| {
    if let tauri::WindowEvent::Destroyed = event {
        // Stop BlueBubbles on app quit
        let rt = tokio::runtime::Handle::current();
        rt.block_on(async { bluebubbles::disable().await.ok(); });
    }
})
```

- [ ] **Step 3: Build to verify**

```bash
cd apps/desktop && cargo build 2>&1 | head -20
```

- [ ] **Step 4: Commit**

```bash
git add apps/desktop/src-tauri/src/node_client.rs apps/desktop/src-tauri/src/lib.rs
git commit -m "feat(desktop): dynamic caps + BB IPC commands

Node client advertises bluebubbles cap when BB sidecar is running.
Adds enable_bluebubbles, disable_bluebubbles, bluebubbles_status
Tauri IPC commands for frontend integration."
```

---

## Task 10: Rust Tray iMessage Status

**Files:**
- Modify: `apps/desktop/src-tauri/src/tray.rs`

- [ ] **Step 1: Add iMessage status line to tray**

Replace the `build_tray_menu` function in `apps/desktop/src-tauri/src/tray.rs` to show both node and iMessage status:

```rust
fn build_tray_menu(app: &AppHandle, status_label: &str) -> tauri::menu::Menu<tauri::Wry> {
    let bb_status = crate::bluebubbles::get_status();
    let bb_label = format!("iMessage: {}", if bb_status.is_empty() { "disabled" } else { &bb_status });

    tauri::menu::MenuBuilder::new(app)
        .item(&tauri::menu::MenuItem::with_id(app, "title", "Isol8 Desktop", false, None::<&str>).unwrap())
        .separator()
        .item(&tauri::menu::MenuItem::with_id(app, "node-status", status_label, false, None::<&str>).unwrap())
        .item(&tauri::menu::MenuItem::with_id(app, "bb-status", &bb_label, false, None::<&str>).unwrap())
        .separator()
        .item(&tauri::menu::MenuItem::with_id(app, "quit", "Quit", true, None::<&str>).unwrap())
        .build()
        .unwrap()
}
```

- [ ] **Step 2: Build to verify**

```bash
cd apps/desktop && cargo build 2>&1 | head -20
```

- [ ] **Step 3: Commit**

```bash
git add apps/desktop/src-tauri/src/tray.rs
git commit -m "feat(desktop): show iMessage status in system tray"
```

---

## Task 11: Frontend Provider Registration

**Files:**
- Modify: `apps/frontend/src/lib/channels.ts`
- Modify: `apps/frontend/src/components/control/panels/channels-types.ts`

- [ ] **Step 1: Add bluebubbles to Provider type**

In `apps/frontend/src/lib/channels.ts`, line 10:

```typescript
export type Provider = "telegram" | "discord" | "slack" | "bluebubbles";
```

Line 12:
```typescript
export const PROVIDERS: Provider[] = ["telegram", "discord", "slack", "bluebubbles"];
```

Lines 14-18, add to PROVIDER_LABELS:
```typescript
export const PROVIDER_LABELS: Record<Provider, string> = {
  telegram: "Telegram",
  discord: "Discord",
  slack: "Slack",
  bluebubbles: "iMessage",
};
```

- [ ] **Step 2: Add bluebubbles to CHANNEL_CONFIG_FIELDS**

In `apps/frontend/src/components/control/panels/channels-types.ts`, add after the `nostr` entry (around line 127):

```typescript
bluebubbles: [
  {
    key: "serverUrl",
    label: "Server URL",
    placeholder: "http://localhost:1234",
    sensitive: false,
    help: "BlueBubbles server URL (auto-configured when using desktop app)",
  },
  {
    key: "password",
    label: "Password",
    placeholder: "BlueBubbles API password",
    sensitive: true,
    help: "BlueBubbles API password (auto-configured when using desktop app)",
  },
],
```

- [ ] **Step 3: Lint and type-check**

```bash
cd apps/frontend && pnpm run lint && pnpm run build
```

- [ ] **Step 4: Commit**

```bash
git add apps/frontend/src/lib/channels.ts apps/frontend/src/components/control/panels/channels-types.ts
git commit -m "feat(frontend): register bluebubbles/iMessage as channel provider"
```

---

## Task 12: Frontend iMessage Wizard Steps

**Files:**
- Modify: `apps/frontend/src/components/channels/BotSetupWizard.tsx`

- [ ] **Step 1: Add iMessage step IDs**

In `apps/frontend/src/components/channels/BotSetupWizard.tsx`, extend the `StepId` type (line 201) to include iMessage-specific steps:

```typescript
type StepId = "intro" | "discord-intents" | "slack-manifest" | "token" | "connecting" | "pair" | "done"
  | "imessage-permissions" | "imessage-enabling" | "imessage-manual";
```

- [ ] **Step 2: Add bluebubbles to Provider type and PROVIDER_STEPS**

Add `"bluebubbles"` to the local `Provider` type (line 17):

```typescript
type Provider = "telegram" | "discord" | "slack" | "bluebubbles";
```

Extend `PROVIDER_STEPS` (line 210):

```typescript
const PROVIDER_STEPS: Record<Provider, StepId[]> = {
  telegram: ["intro", "token", "connecting", "pair", "done"],
  discord:  ["intro", "discord-intents", "token", "connecting", "pair", "done"],
  slack:    ["slack-manifest", "token", "connecting", "pair", "done"],
  bluebubbles: typeof window !== "undefined" && (window as any).__TAURI__
    ? ["intro", "imessage-permissions", "imessage-enabling", "pair", "done"]
    : ["intro", "imessage-manual", "connecting", "pair", "done"],
};
```

- [ ] **Step 3: Add step render functions**

Add render functions for the iMessage-specific steps. Place them alongside the existing `renderIntro`, `renderToken`, etc.:

```tsx
function renderImessagePermissions() {
  return (
    <div className="space-y-4">
      <h3 className="text-lg font-medium">macOS Permissions</h3>
      <p className="text-sm text-muted-foreground">
        iMessage requires Full Disk Access so BlueBubbles can read your messages.
      </p>
      <ol className="list-decimal list-inside space-y-2 text-sm">
        <li>Open <strong>System Settings &gt; Privacy &amp; Security &gt; Full Disk Access</strong></li>
        <li>Enable access for <strong>Isol8</strong></li>
      </ol>
      <Button onClick={() => {
        // Open System Settings via Tauri shell plugin
        (window as any).__TAURI__?.invoke("plugin:shell|open", {
          path: "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"
        });
      }} variant="outline" size="sm">
        Open System Settings
      </Button>
      <div className="pt-4">
        <Button onClick={() => goToStep("imessage-enabling")}>
          I&apos;ve enabled Full Disk Access
        </Button>
      </div>
    </div>
  );
}

function renderImessageEnabling() {
  const [status, setStatus] = useState<string>("starting");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function enableBB() {
      try {
        const password = await (window as any).__TAURI__?.invoke("enable_bluebubbles", { ownerId: user?.id });
        if (cancelled) return;
        // BB is running, now patch the config
        await api.patchConfig({
          channels: { bluebubbles: { enabled: true, password } }
        });
        // Poll channels.status until running
        setStatus("connecting");
        // The existing connecting step logic handles polling
        goToStep("pair");
      } catch (e: any) {
        if (!cancelled) setError(e?.message || "Failed to start iMessage");
      }
    }
    enableBB();
    return () => { cancelled = true; };
  }, []);

  if (error) {
    return (
      <div className="space-y-4">
        <p className="text-sm text-destructive">{error}</p>
        <Button onClick={() => { setError(null); goToStep("imessage-enabling"); }}>
          Retry
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-medium">Setting up iMessage...</h3>
      <p className="text-sm text-muted-foreground">
        {status === "starting" && "Starting BlueBubbles..."}
        {status === "connecting" && "Connecting to your agent..."}
      </p>
      <div className="animate-spin h-6 w-6 border-2 border-primary border-t-transparent rounded-full" />
    </div>
  );
}

function renderImessageManual() {
  // Manual fallback for non-desktop users
  return (
    <div className="space-y-4">
      <h3 className="text-lg font-medium">Manual BlueBubbles Setup</h3>
      <p className="text-sm text-muted-foreground">
        iMessage requires BlueBubbles running on a Mac.{" "}
        <a href="https://bluebubbles.app/install" target="_blank" rel="noopener" className="underline">
          Install BlueBubbles
        </a>, then enter the connection details below.
      </p>
      {renderToken()} {/* Reuses the existing token step for serverUrl + password fields */}
    </div>
  );
}
```

- [ ] **Step 4: Add step routing**

In the step rendering switch (around line 887), add:

```tsx
{step === "imessage-permissions" && renderImessagePermissions()}
{step === "imessage-enabling" && renderImessageEnabling()}
{step === "imessage-manual" && renderImessageManual()}
```

- [ ] **Step 5: Add iMessage intro content**

In the existing `renderIntro()` function, add a case for bluebubbles:

```tsx
{provider === "bluebubbles" && (
  <p className="text-sm text-muted-foreground">
    Connect your agent to iMessage via BlueBubbles.
    {(window as any).__TAURI__
      ? " Your desktop app will manage everything automatically."
      : " You'll need BlueBubbles running on a Mac."}
  </p>
)}
```

- [ ] **Step 6: Lint and build**

```bash
cd apps/frontend && pnpm run lint && pnpm run build
```

- [ ] **Step 7: Commit**

```bash
git add apps/frontend/src/components/channels/BotSetupWizard.tsx
git commit -m "feat(frontend): add iMessage wizard steps to BotSetupWizard

Desktop path: intro → permissions → enabling (auto) → pair → done.
Manual path: intro → manual-setup → connecting → pair → done.
Detects Tauri via window.__TAURI__ to choose the right flow."
```

---

## Task 13: End-to-End Verification

**Goal:** Verify the full stack works, from Tauri app launch to iMessage delivery.

- [ ] **Step 1: Start local development environment**

```bash
./scripts/local-dev.sh
```

- [ ] **Step 2: Launch Tauri desktop app**

```bash
cd apps/desktop && cargo tauri dev
```

- [ ] **Step 3: Verify desktop shell + auth**

- App launches, loads localhost:3000 or dev.isol8.co
- Sign in via Clerk
- System tray shows "Node: connecting..."
- After auth, tray updates to "Node: connected"
- `window.__TAURI__` is detectable in browser console

- [ ] **Step 4: Verify node connection**

- Check backend logs for `handle_node_connect` — node should connect with `caps: ["system"]`
- Check that `tools.deny` is patched (remove `"nodes"`) in the container's `openclaw.json`

- [ ] **Step 5: Verify agent routes through node**

- Send a chat message asking the agent to run `echo hello` or `ls -la`
- Backend should call `sessions.patch` with `execNode`/`execHost: "node"`
- `node.invoke.request` should reach the desktop app
- Command should execute on the Mac (check Tauri console output)
- Result should return to the agent

- [ ] **Step 6: Verify exec approval**

- Ask the agent to run an unknown command (not in the 73 safe binaries)
- macOS dialog should appear: Deny / Allow Once / Allow Always
- Test each button — Deny should fail the command, Allow Once should succeed once, Allow Always should persist

- [ ] **Step 7: Enable iMessage**

- In the chat UI, go to channels, click "Add iMessage"
- Wizard should detect desktop app and show permissions step
- Grant Full Disk Access (if not already done)
- Click "I've enabled Full Disk Access"
- Wizard should download + start BlueBubbles, auto-configure, advance to pairing
- Tray should show "Node: connected | iMessage: connected"

- [ ] **Step 8: Verify iMessage pairing**

- From Messages.app on the same Mac, DM a test number/contact that the agent would respond to
- Or use the pairing flow: DM the agent, get a pairing code, enter it in the wizard
- Verify the pairing completes successfully

- [ ] **Step 9: Verify iMessage messaging**

- Send a message via iMessage to the paired identity
- Verify: BB webhook → backend relay → container → agent processes → agent replies → BB REST API (via proxy) → iMessage delivered

- [ ] **Step 10: Verify disconnect/reconnect**

- Quit the Tauri app
- Verify: backend patches `channels.bluebubbles.enabled = false`, tools.deny re-adds `"nodes"`
- Frontend shows "iMessage unavailable" and "Local tools unavailable"
- Relaunch Tauri app
- Verify: node reconnects, BB restarts, channels re-enabled, already-paired identities work without re-pairing

- [ ] **Step 11: Commit any fixes from testing**

```bash
git add -A
git commit -m "fix: adjustments from end-to-end testing"
```

---

## Execution Dependencies

```
Task 1 (branch consolidation)
  └─> Task 2 (path fix)
  └─> Tasks 3-6 (backend, can run in parallel)
  └─> Tasks 7-10 (Rust, can run in parallel with backend)
  └─> Tasks 11-12 (frontend, can run in parallel with backend + Rust)
       └─> Task 13 (E2E verification, depends on all above)
```

Tasks 3-6 (backend), 7-10 (Rust), and 11-12 (frontend) are independent and can be dispatched in parallel after Task 1 completes.
