# Desktop App: Per-User Local Tools for Personal and Org Accounts

**Date:** 2026-04-12
**Status:** Draft

## Problem

The desktop app's node connection (local tool execution on the user's Mac) is currently tied to `owner_id`, which is `org_id` for org members. This means:

1. In an org, if Alice connects her Mac, ALL org members see "Local tools available" and all their agent sessions can invoke commands on Alice's Mac.
2. If Alice disconnects, node tools are disabled for everyone (the config patch toggles the deny list globally on the shared container).
3. There's no per-member scoping — the system doesn't track which user owns which node.

## Solution

Use OpenClaw's built-in `execNode` session field to pin each user's agent sessions to their own node. When a user connects their Mac via the desktop app, the backend:

1. Registers the node with a user-identifiable nodeId on the shared container
2. Calls `sessions.patch` with `execNode: <nodeId>` and `execHost: "node"` on the user's sessions
3. The agent's `exec` tool (bash/shell execution) automatically routes to the bound node
4. OpenClaw enforces this as a hard constraint — if the agent tries to target a different node, it throws an error

This works for both personal accounts (one user = one container = one node, trivial case) and org accounts (multiple users share one container, each with their own node binding).

## Architecture

### Node connection lifecycle

**On desktop app connect:**

```
Desktop App (Alice)
  → sends Clerk JWT via API Gateway WS
  → Lambda authorizer extracts user_id + org_id
  → Backend websocket_chat.py:
      owner_id = org_id or user_id
      user_id  = always the individual member
  → Backend handle_node_connect(owner_id, user_id, connection_id, connect_params):
      1. Resolve container for owner_id
      2. Create NodeUpstreamConnection to container
      3. Node registers with nodeId = device.id (from Ed25519 keypair)
         displayName = "<user's name> | Isol8 Desktop"
      4. Store mapping: user_id → { nodeId, connection_id }
      5. Broadcast node_status:connected to ONLY Alice's frontend connections
      6. Increment node_count for owner_id; if first node, patch config to enable node tools
```

**On chat message (user has connected Mac):**

```
Alice sends "run whoami"
  → Backend _process_agent_chat_background:
      1. Check: does user_id have a connected node? → Yes, nodeId = "abc123..."
      2. Check in-memory cache: has session_key been patched with this nodeId? → No
      3. Call sessions.patch RPC:
           { sessionKey, execNode: "abc123...", execHost: "node" }
      4. Add session_key to patched cache
      5. Call chat.send RPC as normal
  → Container agent runs:
      1. Agent calls exec tool (system.run)
      2. exec tool reads session.execNode → "abc123..."
      3. exec tool reads session.execHost → "node"
      4. Dispatches node.invoke.request to nodeId "abc123..."
  → Backend NodeUpstreamConnection relays to Alice's desktop app
  → Alice's Mac executes whoami, returns result
```

**On chat message (user has NO connected Mac):**

```
Bob sends "run whoami"
  → Backend checks: does user_id have a connected node? → No
  → Skip sessions.patch
  → Call chat.send as normal
  → Agent runs exec tool with default execHost (local)
  → Command runs on the container
```

**On desktop app disconnect:**

```
Alice closes desktop app
  → Backend handle_node_disconnect(connection_id, owner_id, user_id):
      1. Remove user_id → nodeId mapping
      2. Clear all session_key entries for this user from the patched cache
      3. Call sessions.patch on known sessions: { execNode: null, execHost: null }
      4. Broadcast node_status:disconnected to Alice's frontend connections
      5. Decrement node_count for owner_id; if zero, patch config to re-disable node tools
```

### Per-user node status broadcasting

Currently `broadcast_to_user(owner_id, {"type": "node_status", ...})` sends to ALL frontend connections for the owner (all org members).

Change: introduce `broadcast_to_member(owner_id, user_id, message)` that filters to only the specific member's frontend connections. The connection pool already tracks per-member connections via `_parse_session_key()` which extracts `member_id` from org session keys.

For personal accounts: `user_id == owner_id`, so `broadcast_to_member` behaves identically to `broadcast_to_user`.

### Reference-counted config patching

Currently:
- `handle_node_connect` → `patch_openclaw_config(owner_id, {"tools": {"deny": ["canvas"]}})`
- `handle_node_disconnect` → `patch_openclaw_config(owner_id, {"tools": {"deny": ["canvas", "nodes"]}})`

This breaks with multiple users: Alice disconnects, Bob's node tools are disabled.

Change: track `_node_count: dict[str, int]` (owner_id → count of active node connections).
- On connect: increment. If `0 → 1`, patch config to enable node tools.
- On disconnect: decrement. If `1 → 0`, patch config to disable node tools.
- If count > 0, skip the config patch on individual connect/disconnect.

### Desktop app changes

The node client (`node_client.rs`) currently sends `displayName: "Isol8 Desktop"` in the connect handshake. This should include the user's name for identification in `node.list`.

Two options for getting the user's name:
1. **Decode the JWT in Rust** — the JWT payload has standard claims but NOT the display name (Clerk JWTs contain `sub`, org claims, but not `name`).
2. **Frontend passes user info via Tauri IPC** — when calling `send_auth_token`, also pass `{ token, displayName, userId }`.

Option 2 is simpler and more reliable. The frontend already has `user.fullName` from Clerk's `useUser()` hook.

**Changes to `lib.rs`:**
- `send_auth_token` accepts `token`, `display_name`, `user_id`
- Passes `display_name` to `NodeClient::new()` for the connect handshake displayName
- `user_id` is stored for logging/debugging

**Changes to `useGateway.tsx`:**
- When calling `__TAURI__.core.invoke("send_auth_token", ...)`, include `{ token, displayName: user.fullName, userId: user.id }`

### Session patching cache

In-memory `dict[str, str]` on the backend: `session_key → nodeId`. Tracks which sessions have been patched with which node binding.

- **On chat message**: check cache. If `session_key` not in cache OR cached nodeId differs from current node → call `sessions.patch`. Update cache.
- **On node disconnect**: iterate cache, clear entries for the disconnecting user's sessions, call `sessions.patch` with `execNode: null, execHost: null` for each.
- **On backend restart**: cache starts empty. First message per session re-patches (idempotent — session already has the value from before restart).

Cache lifetime is tied to the backend process — same as `_node_upstreams` and other in-memory WebSocket state. No DynamoDB persistence needed.

## Files to modify

### Backend

| File | Change |
|------|--------|
| `routers/websocket_chat.py` | Pass `user_id` to `handle_node_connect`. Before `chat.send`, check node binding and call `sessions.patch` if needed. |
| `routers/node_proxy.py` | Accept `user_id` param. Track `_user_nodes: dict[str, dict]` (user_id → {nodeId, connection_id}). Track `_node_count: dict[str, int]` (owner_id → count). Per-user broadcast. Reference-counted config patches. |
| `core/gateway/connection_pool.py` | Add `broadcast_to_member(owner_id, user_id, message)` method that filters to a specific member's frontend connections. |
| `core/gateway/node_connection.py` | Include user's displayName in the node connect params. |

### Desktop app (on `feat/desktop-app` branch)

| File | Change |
|------|--------|
| `src/lib.rs` | `send_auth_token` accepts display_name + user_id. Passes display_name to NodeClient. Remove node_proxy references (already done in uncommitted work). |
| `src/node_client.rs` | Accept dynamic displayName in `new()`. Use it in connect handshake. |

### Frontend (on `main`)

| File | Change |
|------|--------|
| `src/hooks/useGateway.tsx` | Pass `displayName` and `userId` alongside `token` in the `send_auth_token` Tauri IPC call. |

## Security

- **`execNode` is a hard constraint**: OpenClaw throws an error if the agent tries to target a different node than the bound one. Alice's commands can never accidentally run on Bob's Mac.
- **Node identity is per-user**: Each user's persistent Ed25519 keypair (stored on EFS per owner_id) produces a unique nodeId. In an org, all users share the same container but each has a distinct node registration.
- **Config patch is reference-counted**: One user disconnecting doesn't disable node tools for other users who still have their Macs connected.
- **Broadcast is per-user**: Only the connecting user sees "Local tools available", not all org members.

## Edge cases

1. **User connects Mac, then switches from personal to org context (or vice versa):** The JWT changes, the WebSocket reconnects with a new owner_id. The old node connection is cleaned up via `$disconnect`. The new connection creates a fresh node binding. Handled by the existing reconnection flow.

2. **Backend restarts while nodes are connected:** Desktop apps reconnect (Rust client has exponential backoff retry). Sessions still have `execNode` set from before the restart. The patching cache starts empty, so the first message re-patches (idempotent). No user-visible disruption beyond a brief reconnection delay.

3. **User has multiple desktop apps connected (e.g., MacBook + Mac Mini):** The second connection would overwrite the `user_id → nodeId` mapping. Last-connected device wins. For the MVP, this is acceptable. Future enhancement: track multiple nodes per user and let the user pick.

4. **Stale `execNode` after unclean disconnect:** If the backend crashes, `execNode` isn't cleared on the session. The user's agent tries to route to a disconnected node and gets "node not connected." Recovery: desktop app reconnects (1-30s), backend re-patches the session with the new (same) nodeId.

## Testing

1. **Personal account**: Connect Mac → send chat message asking agent to run `whoami` → verify it returns the Mac's username (not `root` from the container).
2. **Org account, single member**: Same as personal, but logged in with org context.
3. **Org account, two members**: Alice connects Mac, Bob connects Mac. Alice asks `whoami` → should return Alice's Mac username. Bob asks `whoami` → should return Bob's Mac username. Verify no cross-user execution.
4. **Disconnect handling**: Alice disconnects. Bob's agent should still use Bob's node. Alice's agent should fall back to container-local execution.
5. **Reconnection**: Kill the desktop app process. Wait for reconnection (~1-30s). Send a chat message. Verify it routes to the Mac again.
