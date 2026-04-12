# Desktop App, Node Infrastructure & iMessage Channel — Design Spec

**Date:** 2026-04-11
**Status:** Draft
**Scope:** Full desktop + node + iMessage stack. Personal accounts first, org multi-member supported.

---

## Overview

Ship the Isol8 desktop app (Tauri 2) with three capabilities:

1. **Local tool execution** — the agent in the Fargate container can run shell commands, resolve binaries, and approve/deny exec on the user's Mac via the OpenClaw node protocol
2. **Per-user node routing** — in orgs, each member's Mac routes to their own sessions only; ref-counted config patching manages the shared container's tool availability
3. **iMessage channel** — BlueBubbles server managed as a Tauri sidecar, bridged to the container's OpenClaw BB channel plugin via a reverse HTTP proxy through the node WebSocket

All three capabilities ship together on a single feature branch. Nothing merges to main until the full stack is tested end-to-end.

---

## Current State Assessment

### What Exists

**On main (merged via PRs #159, #161, #163):**
- Frontend desktop auth flow (Clerk → Tauri IPC via `window.__TAURI__`)
- Backend `NodeUpstreamConnection` class (`core/gateway/node_connection.py`, 111 lines)
- Backend `node_proxy.py` (simple single-owner version, 90 lines)
- `connection_pool.broadcast_to_user()`
- `websocket_chat.py` `role:"node"` handshake detection
- `connection_service.py` `connection_type` field

**In `feat/desktop-app` worktree (not merged):**
- Full Tauri 2 app: `lib.rs` (216 lines), `node_client.rs` (297 lines), `node_invoke.rs` (358 lines), `exec_approvals.rs` (219 lines), `tray.rs` (51 lines)
- Native Rust node client using tokio-tungstenite (replaced earlier Electron/loopback approach)
- Exec approval system with persistent store, 73 safe binaries, shell wrapper handling, native macOS dialog
- GitHub Actions build workflow with notarization
- Desktop auth router, frontend auth listeners

**In `worktree-per-user-node` worktree (not merged):**
- Enhanced `node_proxy.py` (198 lines) — per-user node tracking, ref-counted config patches, session binding cache, `broadcast_to_member`
- Enhanced `node_connection.py` (195 lines) — `device_id` attribute from handshake
- Backend tests: `test_node_proxy.py` (159 lines, 5 async test cases)
- Frontend: `useGateway.tsx` passes `userId` + `displayName` via Tauri IPC

### What's Working

- Tauri shell launches, loads web UI, Clerk auth flows through
- Node client connects to gateway, completes hello-ok handshake
- Backend creates upstream WS to container, relays node protocol messages
- Ed25519 device identity generated during provisioning, pre-paired on EFS
- Exec approval dialog appears on Mac for unknown commands

### What's Unverified or Broken

1. **Agent routing through node** — the core "agent calls `exec`, command runs on Mac" flow has not been verified end-to-end. The per-user-node branch adds `sessions.patch` binding with `execHost: "node"` which should make this work, but it's untested.
2. **Branch divergence** — the two worktrees both modify `node_proxy.py`, `websocket_chat.py`, `connection_pool.py`, `useGateway.tsx`. They will conflict on merge.
3. **Tauri Rust code has zero org awareness** — stores one JWT, one connection, no `orgId`/`member`/`owner` concepts. The per-user-node branch's frontend passes `userId` + `displayName`, but the Rust `send_auth_token` handler already accepts these (verified in `lib.rs:49-51`).
4. **Path discrepancy** — ~~device identity spec says `nodes/.node-device-key.pem`, implementation uses `devices/.node-device-key.pem`.~~ Resolved: `devices/` is correct. The old node-identity spec was stale.
5. **The original plan doc (`2026-04-01-desktop-app.md`) is stale** — still references Electron, 0/107 checkboxes, treat as historical context only.

### Design Specs Referenced

- `2026-04-01-desktop-app-design.md` — original design (Electron-era, pre-Tauri migration)
- `2026-04-05-node-device-identity-design.md` — Ed25519 device pairing (approved, implemented)
- `2026-04-12-desktop-per-user-node-design.md` — per-user session binding (draft, partially implemented)

---

## Branch Strategy

**Step 1:** Merge `worktree-per-user-node` to main (4 clean commits on recent base, trivial merge).

**Step 2:** Create a new feature branch `feat/desktop-imessage` off updated main.

**Step 3:** Rebase `feat/desktop-app` onto `feat/desktop-imessage`. Conflict resolution:
- `node_proxy.py` — per-user-node version wins (strict superset)
- `websocket_chat.py` — per-user-node version wins (adds user_id wiring)
- `connection_pool.py` — both additions compatible, keep both
- `useGateway.tsx` — manual merge (node-status listener from feat/desktop-app + identity-passing from per-user-node)

**Step 4:** Add iMessage/BlueBubbles work on top.

**Step 5:** Test full stack end-to-end. Only merge to main when confident.

---

## Phase 1: Branch Consolidation

Combine the two worktrees into a single branch with no regressions.

### Files from `feat/desktop-app` (Tauri — purely additive, no conflicts)

```
apps/desktop/                          # Entire Tauri app (new directory)
  src-tauri/src/lib.rs                 # App entry, IPC handlers, auth state
  src-tauri/src/main.rs                # Tauri main
  src-tauri/src/node_client.rs         # Rust OpenClaw node client
  src-tauri/src/node_invoke.rs         # Local command execution handlers
  src-tauri/src/exec_approvals.rs      # Exec approval system
  src-tauri/src/tray.rs                # System tray
  src-tauri/Cargo.toml                 # Rust deps
  src-tauri/tauri.conf.json            # Tauri config
  src-tauri/capabilities/              # macOS entitlements
  src-tauri/icons/                     # App icons
  package.json                         # pnpm scripts
.github/workflows/desktop-build.yml   # CI: build + notarize
apps/backend/routers/desktop_auth.py   # Clerk sign-in token endpoint
apps/frontend/src/components/auth/DesktopAuthListener.tsx
apps/frontend/src/hooks/useDesktopAuth.ts
apps/frontend/src/app/auth/desktop-callback/page.tsx
apps/frontend/src/types/electron.d.ts  # (rename to tauri.d.ts)
```

### Files from `worktree-per-user-node` (backend — wins on conflict)

```
apps/backend/routers/node_proxy.py               # Per-user version (replaces feat/desktop-app's)
apps/backend/core/gateway/node_connection.py      # + device_id attribute
apps/backend/core/gateway/connection_pool.py      # + broadcast_to_member()
apps/backend/routers/websocket_chat.py            # + user_id wiring, sessions.patch
apps/frontend/src/hooks/useGateway.tsx            # + userId/displayName IPC
apps/backend/tests/unit/routers/test_node_proxy.py # Tests
```

### Manual merge: `useGateway.tsx`

Combine from feat/desktop-app:
- `nodeConnected` state
- `node_status` message handler
- `onNodeStatus` listener

With from per-user-node:
- `useUser()` import
- `displayName` and `userId` passed to `send_auth_token` Tauri IPC invoke

### Post-merge fix: path discrepancy

Reconcile `devices/` vs `nodes/` for the key path. Check what the container's OpenClaw actually expects in `paired.json` and align. The implementation uses `devices/` — if that works, update the spec. If the container expects `nodes/`, update the code.

---

## Phase 2: Desktop App Shell & Auth

The Tauri shell is already built. This phase is about verifying it works correctly after the branch merge.

### What's Already Implemented

| Component | File | Status |
|-----------|------|--------|
| App entry + lifecycle | `lib.rs` | Complete |
| Clerk auth via webview | `lib.rs` (OAuth intercept plugin) | Complete |
| Auth token IPC | `lib.rs:send_auth_token` | Complete (accepts token, display_name, user_id) |
| Deep links (`isol8://auth`) | `lib.rs` | Complete |
| System tray | `tray.rs` | Complete |
| Desktop detection | `lib.rs:is_desktop` | Complete |
| Frontend auth listener | `DesktopAuthListener.tsx` | Complete |
| Backend sign-in token | `desktop_auth.py` | Complete |

### Verification Checklist

- [ ] Tauri app launches, loads `dev.isol8.co/chat` (or localhost:3000)
- [ ] Clerk sign-in works in webview (including Google/Apple OAuth popups)
- [ ] JWT token passes from webview to Rust main process via IPC
- [ ] `isol8://auth` deep link works for OAuth callback
- [ ] System tray shows with status
- [ ] App appears in macOS Dock with correct icon
- [ ] `window.__TAURI__` is detectable from the frontend
- [ ] `userId` and `displayName` reach the Rust `send_auth_token` handler

---

## Phase 3: Node Infrastructure

This is the core of the desktop app's value — the agent in the cloud can execute tools on the user's Mac.

### OpenClaw Node Protocol

The node is a WebSocket client connecting with `role: "node"`. It declares capabilities and commands, then handles invoke requests.

**Wire protocol:**

```
Tauri (Mac)                         Backend                         OpenClaw Container
     │                                │                                │
     │ WS connect (role:"node")       │                                │
     │──────────────────────────────>│ upstream WS to container       │
     │                                │──────────────────────────────>│
     │                                │    connect.challenge (nonce)   │
     │                                │<──────────────────────────────│
     │ connect { role:"node",         │                                │
     │   caps:["system"],             │                                │
     │   commands:[5 system cmds],    │                                │
     │   device:{id, sig, pubkey},    │                                │
     │   auth:{token: clerk_jwt} }    │                                │
     │──────────────────────────────>│ relay connect                  │
     │                                │──────────────────────────────>│
     │                                │         hello-ok               │
     │<──────────────────────────────│<──────────────────────────────│
     │                                │                                │
     │   ... agent calls exec ...     │                                │
     │                                │                                │
     │   node.invoke.request          │                                │
     │   {command:"system.run",       │                                │
     │    params:{cmd:"ls -la"}}      │                                │
     │<──────────────────────────────│<──────────────────────────────│
     │   [execute on Mac]             │                                │
     │   node.invoke.result           │                                │
     │   {ok:true, payload:"..."}     │                                │
     │──────────────────────────────>│──────────────────────────────>│
```

### Tool Routing

Routing is **session-level, not tool-level.** There's no `runsOnNode: true` property.

1. User sends a chat message
2. Backend checks `get_user_node(user_id)` — is a Mac connected?
3. If yes, calls `sessions.patch` with `{execNode: nodeId, execHost: "node"}` before forwarding to `chat.send`
4. When agent calls `exec`, OpenClaw reads `session.execHost` → dispatches `node.invoke.request` to the bound node
5. If no node → session has no `execHost` → exec runs locally in container

The `tools.deny: ["nodes"]` config entry toggles visibility. When present, the agent doesn't see node-dependent tools.

### Device Identity

Per the approved spec (`2026-04-05-node-device-identity-design.md`):
- Persistent Ed25519 keypair generated during container provisioning
- Public key pre-written to `devices/paired.json` on EFS
- Private key at `devices/.node-device-key.pem` on EFS
- Backend loads key, signs v2 challenge payload, container validates against paired devices
- `deviceId` = SHA-256 hex of raw Ed25519 public key

### Per-User Node Routing (Orgs)

Per the design (`2026-04-12-desktop-per-user-node-design.md`):

**Data structures in `node_proxy.py`:**
```python
_node_upstreams: dict[str, NodeUpstreamConnection]  # connection_id → upstream
_user_nodes: dict[str, dict]      # user_id → {nodeId, connection_id, owner_id}
_node_count: dict[str, int]       # owner_id → active node count (ref-counted)
_patched_sessions: dict[str, str] # session_key → nodeId (cache)
```

**Lifecycle:**
- **Connect:** Store `_user_nodes[user_id]`, increment `_node_count[owner_id]`, on 0→1 transition patch config to remove `"nodes"` from `tools.deny`, broadcast `node_status` to that member only via `broadcast_to_member`
- **Chat message:** Check `get_user_node(user_id)`, if connected and session not already patched, call `sessions.patch` with `execNode`/`execHost: "node"`, cache in `_patched_sessions`
- **Disconnect:** Remove `_user_nodes[user_id]`, best-effort clear `execNode` on all patched sessions for that user, decrement `_node_count[owner_id]`, on 1→0 transition re-add `"nodes"` to `tools.deny`, broadcast disconnect to that member

**Org scenario:**
- Alice and Bob in same org, same container
- Alice connects Mac → `_user_nodes["alice"]`, `_node_count["org_owner"] = 1`, config patched
- Bob connects Mac → `_user_nodes["bob"]`, `_node_count["org_owner"] = 2`
- Alice chats → `sessions.patch` binds to Alice's node. Bob chats → binds to Bob's node.
- Alice disconnects → `_node_count` = 1 (config stays patched), Alice's sessions cleared
- Bob disconnects → `_node_count` = 0, `"nodes"` re-added to deny

### Tools Available via Node

| Command | Handler | What It Does |
|---------|---------|-------------|
| `system.run` | `node_invoke.rs` | Shell command execution with exec approval gating, 200KB output cap, timeout, env sanitization |
| `system.run.prepare` | `node_invoke.rs` | Pre-validates a command (resolves binary, checks approval) |
| `system.which` | `node_invoke.rs` | Resolves binary path on the Mac |
| `system.execApprovals.get` | `node_invoke.rs` | Returns approval allowlist snapshot |
| `system.execApprovals.set` | `node_invoke.rs` | Updates approval allowlist (currently stubbed — returns `{ok:true}`) |

### Exec Approval Security

Three levels: `Deny` (block all), `Allowlist` (prompt for unknown), `Full` (allow all).

- 73 pre-approved safe binaries (read-only commands, git, docker, language runtimes)
- Shell wrapper handling: `sh -c "inner_cmd"` checks the inner command too
- Persistent store at `~/.isol8/exec-approvals.json`
- Native macOS dialog via `osascript`: Deny / Allow Once / Allow Always
- Environment sanitized: removes `ELECTRON_RUN_AS_NODE`, `NODE_OPTIONS`, `TAURI_ENV_DEBUG`

### Reconnection & Liveness

- Rust client reconnects with exponential backoff: 1s → 2s → 4s → ... → 30s max
- On disconnect mid-invoke: call fails (no queue, no fallback to container)
- Backend clears sessions and re-adds `"nodes"` to deny
- On reconnect: caps re-advertised, config re-patched, sessions re-bound on next chat message
- Already-paired device identity persists on EFS

### Verification Checklist

- [ ] Node client connects to gateway, hello-ok completes
- [ ] Device identity challenge-response succeeds
- [ ] `tools.deny` is patched to remove `"nodes"` on connect
- [ ] Agent sees `exec` tool when node is connected
- [ ] Agent calls `exec` → `sessions.patch` fired → `node.invoke.request` reaches Mac
- [ ] Command executes on Mac, output returns to agent
- [ ] Exec approval dialog appears for unknown commands
- [ ] Allow Always persists across sessions
- [ ] `tools.deny` re-adds `"nodes"` on disconnect
- [ ] Agent no longer sees node tools after disconnect
- [ ] Reconnection works after network drop
- [ ] (Org) Two members connect independently, sessions route to correct nodes
- [ ] (Org) One member disconnects, other's node still works

---

## Phase 4: iMessage Channel via BlueBubbles

### Background

In a native OpenClaw Mac install, the gateway and BlueBubbles both run `localhost`. In Isol8, the container is in Fargate and BlueBubbles is on the user's Mac — different machines with no direct IP reachability. This design bridges that gap via the existing node WebSocket.

### Architecture

```
User's Mac (Tauri Desktop App)
┌──────────────────────────────────────────┐
│  Tauri Main Process                      │
│  ├── Node Client (system.run, etc.)      │
│  ├── BlueBubbles Manager (NEW)           │
│  │   ├── Download/install BB .app        │
│  │   ├── Start/stop BB process           │
│  │   ├── Health polling                  │
│  │   └── Auto-configure URL+password     │
│  └── Tray (node + iMessage status)       │
│                                          │
│  BlueBubbles Server (sidecar)            │
│  ├── REST API on localhost:1234          │
│  ├── Reads ~/Library/Messages/chat.db    │
│  └── Sends via Messages.app (AppleScript)│
└──────────┬───────────────────────────────┘
           │ WS (role:"node")
           ▼
┌──────────────────────────────────────────┐
│  Isol8 Backend                           │
│  ├── Detects "bluebubbles" in node caps  │
│  ├── Patches openclaw.json with BB config│
│  ├── HTTP proxy endpoint (REST calls)    │
│  └── Webhook relay endpoint (inbound)    │
└──────────┬───────────────────────────────┘
           │ upstream WS
           ▼
┌──────────────────────────────────────────┐
│  OpenClaw Container (Fargate)            │
│  ├── BlueBubbles channel plugin (bundled)│
│  │   ├── REST calls → backend proxy      │
│  │   │   → node invoke → Mac → BB API   │
│  │   ├── Webhooks ← backend relay        │
│  │   │   ← BB on Mac                    │
│  │   └── Full plugin features: pairing,  │
│  │       allowlists, typing indicators,  │
│  │       reactions, thread replies        │
│  └── Agent processes iMessage like any   │
│      other channel                       │
└──────────────────────────────────────────┘
```

### Network Connectivity

**Outbound REST (Container → Mac) — via node invoke proxy:**

```
OpenClaw Container                  Backend (EC2)                    Tauri (Mac)
       │                                │                                │
       │ HTTP request to serverUrl      │                                │
       │──────────────────────────────>│                                │
       │                                │ node.invoke.request            │
       │                                │ {cmd:"http.proxy",             │
       │                                │  method, path, headers, body}  │
       │                                │──────────────────────────────>│
       │                                │                                │ HTTP to
       │                                │                                │ localhost:1234
       │                                │     node.invoke.result         │
       │   HTTP response                │     {status, headers, body}    │
       │<──────────────────────────────│<──────────────────────────────│
```

- `serverUrl` in openclaw.json = `http://<backend-alb>/api/v1/proxy/bluebubbles/{owner_id}`
- Authenticates via shared secret: the BB password (known to container from `openclaw.json`, to backend from node connect handshake). Passed as `Authorization: Bearer {bb_password}` header.
- Backend looks up `_user_nodes[user_id]` to find the connected node
- Sends `http.proxy` invoke command, returns the response
- No node connected → 503

**Inbound Webhooks (Mac → Container) — via backend HTTP relay:**

```
BlueBubbles (Mac)                   Backend (EC2)                   OpenClaw Container
       │                                │                                │
       │ POST webhook                   │                                │
       │──────────────────────────────>│                                │
       │  https://api.isol8.co/        │ Cloud Map → container IP       │
       │  api/v1/channels/bb/          │                                │
       │  webhook/{owner_id}           │ HTTP POST (internal VPC)       │
       │                                │──────────────────────────────>│
       │          200 OK                │         200 OK                 │
       │<──────────────────────────────│<──────────────────────────────│
```

- Webhook URL = `https://api.isol8.co/api/v1/channels/bluebubbles/webhook/{owner_id}?password={pw}`
- Backend validates BB password from query param (not Clerk JWT — called by BB process)
- Forwards to `http://<container-ip>:3000/bluebubbles-webhook?password={pw}`

### Tauri Sidecar Management

**New module: `bluebubbles.rs`**

| Function | Purpose |
|----------|---------|
| `download_bluebubbles()` | Fetch `.app` from GitHub releases to `~/Library/Application Support/co.isol8.desktop/BlueBubbles/`, verify checksum |
| `start_bluebubbles()` | Spawn child process, poll `localhost:1234/api/v1/server/info` until healthy (30s timeout) |
| `stop_bluebubbles()` | Graceful shutdown, kill if needed |
| `configure_bluebubbles(password, webhook_url)` | REST API calls to set BB password + webhook URL |
| `health_check()` | Periodic health poll |

Lifecycle:
- BB starts/stops with the Tauri app (auto-start if previously enabled)
- Crash recovery: restart up to 3 times with exponential backoff (1s, 2s, 4s)
- Password randomly generated, stored in `tauri-plugin-store`
- Tray shows iMessage status: disconnected / starting / connected / error

**macOS permissions:**
- **Full Disk Access** (required): BB reads `~/Library/Messages/chat.db`
- **Accessibility** (optional): AppleScript on some macOS versions
- Guided permission prompt on first enable, links to System Settings > Privacy & Security

**New node invoke command: `http.proxy`**

Added to `node_invoke.rs`:
- Receives `{method, path, query, headers, body}` from `node.invoke.request`
- Makes HTTP request to `http://localhost:1234{path}?{query}` using `reqwest`
- Returns `{status, headers, body}` as `node.invoke.result`

**Extended node capabilities:**

`node_client.rs` adds `"bluebubbles"` to `caps` array when BB sidecar is running. On BB crash/stop, caps update to remove it.

### Frontend Channel UI

**Provider registration:**

| File | Change |
|------|--------|
| `src/lib/channels.ts` | Add `"bluebubbles"` to `Provider` type, `PROVIDERS`, `PROVIDER_LABELS` ("iMessage") |
| `src/components/control/panels/channels-types.ts` | Add `bluebubbles` to `CHANNEL_CONFIG_FIELDS` (serverUrl, password — auto-configured, hidden in desktop flow) |

**Setup wizard (two paths):**

Desktop detected (`window.__TAURI__`):
```
intro → permissions → enabling → pair → done
```

| Step | Content |
|------|---------|
| `intro` | "iMessage connects through your desktop app via BlueBubbles" |
| `permissions` | Check/prompt Full Disk Access |
| `enabling` | IPC `enable_bluebubbles` → download BB → start → auto-configure → poll `channels.status` until running |
| `pair` | Standard 8-char pairing code |
| `done` | "iMessage connected. DM your agent from Messages." |

No desktop (manual fallback):
```
intro → manual-setup → pair → done
```
Collects `serverUrl` + `password`. User configures webhook URL manually.

### Backend Changes

**New: BlueBubbles HTTP Proxy** (`routers/bluebubbles_proxy.py`):

```
ANY /api/v1/proxy/bluebubbles/{owner_id}/{path:path}
```
- Accepts any HTTP method
- Authenticates via BB password in `Authorization: Bearer` header
- Sends `node.invoke.request` with command `http.proxy`
- Returns node's response as HTTP
- No node → 503

**New: BlueBubbles Webhook Relay** (added to `routers/channels.py`):

```
POST /api/v1/channels/bluebubbles/webhook/{owner_id}
```
- Validates BB password from query param
- Discovers container via Cloud Map
- Forwards to `http://<container-ip>:3000/bluebubbles-webhook?password={pw}`

**Modified files:**

| File | Change |
|------|--------|
| `routers/channels.py` | Add `"bluebubbles"` to `SUPPORTED_PROVIDERS`. Add webhook relay. |
| `core/containers/config.py` | Add `bluebubbles` block to `write_openclaw_config()` — `enabled: false` by default. |
| `routers/node_proxy.py` | Extend `handle_node_connect`: if `"bluebubbles"` in caps, patch `openclaw.json` with BB channel config. On disconnect, disable. |

**Unchanged (provider-agnostic):** `channel_link_service.py`, `channel_link_repo.py`, `config_patcher.py`, `routers/config.py`

### End-to-End Enable Flow

1. User clicks "Enable iMessage" in BotSetupWizard
2. Frontend detects `window.__TAURI__`, calls `invoke("enable_bluebubbles")`
3. Tauri downloads BB (first time), generates password, spawns BB process
4. Tauri polls BB health, configures password + webhook URL via BB REST API
5. Tauri node client reconnects with `caps: ["system", "bluebubbles"]` + BB password
6. Backend `handle_node_connect` sees `"bluebubbles"` in caps
7. Backend patches `openclaw.json`: `channels.bluebubbles` enabled, serverUrl = proxy, password, webhookPath, dmPolicy = "pairing"
8. Container hot-reloads config via chokidar, BB plugin starts
9. Frontend polls `channels.status` RPC → shows running → wizard advances to pairing
10. User DMs agent from Messages.app → BB webhook → backend relay → container
11. OpenClaw generates pairing code, replies via BB
12. User enters code → `POST /channels/link/bluebubbles/complete` → paired

### Disconnect Behavior

1. User quits Tauri (or Mac sleeps/loses network)
2. Backend detects node disconnect
3. Backend patches `channels.bluebubbles.enabled = false`
4. Container hot-reloads, BB plugin stops
5. Frontend shows "iMessage unavailable — desktop app offline"
6. On reconnect: caps re-advertised, config re-patched, already-paired identities persist

### Verification Checklist

- [ ] BlueBubbles downloads and starts as sidecar
- [ ] BB health check passes at localhost:1234
- [ ] BB password and webhook URL auto-configured
- [ ] `"bluebubbles"` appears in node caps on backend
- [ ] `openclaw.json` patched with BB channel config
- [ ] Container's BB plugin connects to serverUrl (through proxy)
- [ ] Incoming iMessage triggers webhook → backend relay → container
- [ ] Pairing code generated, delivered via iMessage reply
- [ ] Pairing completes, peer added to allowFrom
- [ ] Subsequent messages from paired peer reach the agent
- [ ] Agent replies delivered via iMessage
- [ ] Desktop disconnect disables BB channel
- [ ] Reconnect re-enables without re-pairing
- [ ] Full Disk Access permission prompt shown on first enable

---

## Phase 5: Browser Capability (Optional)

OpenClaw supports `browser.proxy` as an optional node capability. The Tauri client does not currently declare it (`caps: ["system"]` only). This is a natural extension of the node infrastructure.

### What It Would Add

The agent could control a browser on the user's Mac — navigate, click, fill forms, take screenshots, evaluate JS. This runs through the same `node.invoke.request` mechanism as `system.run`.

### Implementation Approach

1. Add `"browser"` to `caps` in `node_client.rs` when a browser is available
2. Add `browser.proxy` command handler in `node_invoke.rs`:
   - Launch headless Chromium or connect to user's Chrome via CDP
   - Handle commands: `navigate`, `click`, `fill`, `screenshot`, `evaluate`, `select`
   - Return results (HTML, screenshots as base64, evaluation results)
3. Backend: enable `browser` config in `openclaw.json` when `"browser"` cap is present (same pattern as `"bluebubbles"`)
4. Tauri: add `reqwest` calls to `localhost:9222` (Chrome DevTools Protocol)

### Deferred

This is not in scope for the current spec. Documenting here as the natural next step once Phases 1-4 ship. The infrastructure (node invoke, dynamic caps, config patching) is identical to what iMessage uses.

---

## Tauri Code Changes Summary

### New Files

| File | Purpose |
|------|---------|
| `bluebubbles.rs` | Sidecar manager: download, spawn, health, configure, crash recovery |

### Extended Files

| File | Change |
|------|--------|
| `node_invoke.rs` | Add `http.proxy` command handler (HTTP to localhost:1234 via reqwest) |
| `node_client.rs` | Add `"bluebubbles"` to caps when BB running; dynamic caps update |
| `lib.rs` | Register `enable_bluebubbles` / `disable_bluebubbles` / `bluebubbles_status` IPC. Wire BB lifecycle to app start/quit. |
| `tray.rs` | Add iMessage status line |
| `Cargo.toml` | Add `reqwest` dependency (for http.proxy + BB REST API calls) |

---

## Backend Code Changes Summary

### New Files

| File | Purpose |
|------|---------|
| `routers/bluebubbles_proxy.py` | HTTP proxy: container → node → Mac → BB REST API |

### Modified Files

| File | Change |
|------|--------|
| `routers/channels.py` | Add `"bluebubbles"` to `SUPPORTED_PROVIDERS`. Add webhook relay endpoint. |
| `core/containers/config.py` | Add `bluebubbles` block (disabled by default) to `write_openclaw_config()` |
| `routers/node_proxy.py` | Handle `"bluebubbles"` cap: patch/unpatch BB channel config on connect/disconnect |

---

## Frontend Code Changes Summary

### Modified Files

| File | Change |
|------|--------|
| `src/lib/channels.ts` | Add `"bluebubbles"` to Provider, PROVIDERS, PROVIDER_LABELS |
| `src/components/control/panels/channels-types.ts` | Add bluebubbles to CHANNEL_CONFIG_FIELDS |
| `src/components/channels/BotSetupWizard.tsx` | Add iMessage steps (desktop auto + manual fallback) |
| `src/hooks/useGateway.tsx` | (Already handled in branch merge — node status + identity passing) |

---

## Scope & Deferrals

### In Scope

- Branch consolidation (per-user-node + feat/desktop-app)
- Tauri desktop app shell & auth (verification)
- Node infrastructure: per-user routing, session binding, device identity, exec approvals
- End-to-end agent-routes-through-node verification
- iMessage channel via BlueBubbles sidecar
- HTTP proxy + webhook relay for BB connectivity
- Personal accounts fully supported
- Org accounts: per-user node routing supported, iMessage per-container (one BB instance)

### Deferred

- **Managed cloud Mac hosting** — HostMyApple or similar. Ship once demand validated.
- **Org multi-member iMessage** — Currently one BB instance per container (last-connected wins for proxy). Per-member BB routing needs per-member instances or multiplexing.
- **Browser capability (`browser.proxy`)** — Documented in Phase 5 but not implemented in this pass.
- **Computer-use** — No OpenClaw built-in capability. Would need MCP-over-node bridge or native node commands. Future work.
- **MCP-over-node bridge** — Proxy user's local MCP servers to the container agent. Not in scope.
- **BlueBubbles auto-update** — Desktop app could check for BB releases. Not in scope.
- **Windows/Linux desktop** — macOS only for now.
- **`system.execApprovals.set` full implementation** — Currently stubbed in `node_invoke.rs`. Low priority.
