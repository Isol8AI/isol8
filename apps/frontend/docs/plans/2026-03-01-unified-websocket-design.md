# Unified WebSocket Architecture

**Date:** 2026-03-01
**Status:** Design approved

## Problem

Isol8's control dashboard uses HTTP polling (`POST /container/rpc`) for every RPC call to the user's OpenClaw gateway. Each call opens a new WebSocket to the gateway, completes a handshake, sends one request, reads the response, and closes. Meanwhile, agent chat uses a separate persistent WebSocket through API Gateway (`wss://ws-dev.isol8.co`).

This causes:
- High latency for control panel operations (handshake overhead per call)
- No real-time updates (polling at 10s intervals)
- Action button responses discarded (fire-and-forget RPC mutations)
- Two disconnected communication paths (HTTP for RPC, WebSocket for chat)

OpenClaw's own web dashboard maintains a single persistent WebSocket to the gateway where everything flows: `req`/`res` for RPC, `event` for broadcasts, and chat. We want to replicate this.

## Design

### Architecture

```
Frontend ── wss://ws-dev.isol8.co ──> API Gateway ──> Backend ── ws://container:18789
   |                                       |                         |
   |  req/res (OpenClaw protocol)          |  proxy                  |  req/res
   |  agent_chat/chunk/done (custom)       |  proxy + usage track    |  /v1/chat/completions
   |  event (forwarded broadcasts)         |  forward                |  event broadcasts
   |  ping/pong (keepalive)                |  handle locally         |
```

One WebSocket on each side. Frontend speaks to our backend through the existing API Gateway WebSocket. Backend maintains one persistent WebSocket per active user to their OpenClaw gateway container.

### Message Protocol

The frontend-to-backend WebSocket carries three categories of messages:

**1. OpenClaw protocol (proxied transparently):**

| Direction | Type | Fields | Purpose |
|-----------|------|--------|---------|
| Frontend -> Backend | `req` | `id` (uuid), `method`, `params` | RPC request (health, channels.status, config.set, etc.) |
| Backend -> Frontend | `res` | `id` (matching uuid), `ok`, `payload`/`error` | RPC response |
| Backend -> Frontend | `event` | `event` (name), `payload` | Gateway broadcast (health updates, channel state changes) |

These match OpenClaw's native WebSocket protocol exactly. The backend proxies them through without translation.

**2. Chat streaming (custom, unchanged):**

| Direction | Type | Fields | Purpose |
|-----------|------|--------|---------|
| Frontend -> Backend | `agent_chat` | `agent_name`, `message` | Start chat with agent |
| Backend -> Frontend | `chunk` | `content` | Streaming response text |
| Backend -> Frontend | `done` | — | Stream complete |
| Backend -> Frontend | `error` | `message` | Error |
| Backend -> Frontend | `heartbeat` | — | Agent working (tool execution) |

Chat stays as a separate message type because it goes through a different backend code path (HTTP to `/v1/chat/completions`, usage tracking, streaming SSE parsing).

**3. Keepalive (custom, unchanged):**

| Direction | Type | Purpose |
|-----------|------|---------|
| Frontend -> Backend | `ping` | Keepalive |
| Backend -> Frontend | `pong` | Keepalive response |

### Backend: GatewayConnectionPool

New module: `core/gateway/connection_pool.py`

Maintains one persistent WebSocket per active user to their OpenClaw gateway.

```python
class GatewayConnection:
    """Single persistent WebSocket to a user's OpenClaw gateway."""

    ws: WebSocketClientProtocol          # websockets client connection
    user_id: str
    container: Container                  # DB record (has gateway_token)
    ip: str                               # container task IP
    _reader_task: asyncio.Task            # background message reader
    _pending_rpcs: Dict[str, asyncio.Future]  # req_id -> Future
    _frontend_connections: Set[str]       # API Gateway connection IDs for this user

    async def connect(self) -> None
        """Open WS, complete OpenClaw handshake, start reader task."""

    async def send_rpc(self, req_id: str, method: str, params: dict) -> None
        """Send {type: req} on gateway WS. Response arrives via reader task."""

    async def wait_for_response(self, req_id: str, timeout: float = 30) -> dict
        """Await the Future for a given req_id."""

    async def close(self) -> None
        """Cancel reader task, close WS."""

    async def _reader_loop(self) -> None
        """Background task: read all messages from gateway WS.

        - type=res: resolve matching Future in _pending_rpcs
        - type=event: forward to all _frontend_connections via Management API
        - unexpected close: attempt reconnect with backoff
        """


class GatewayConnectionPool:
    """Pool of persistent gateway connections, one per active user."""

    _connections: Dict[str, GatewayConnection]  # user_id -> connection
    _lock: asyncio.Lock

    async def get_or_create(self, user_id, container, ip) -> GatewayConnection
        """Return existing connection or create new one (handshake + reader)."""

    async def send_rpc(self, user_id, req_id, method, params) -> dict
        """Send RPC and await response. Resolves container/IP if needed."""

    async def close_user(self, user_id) -> None
        """Close gateway connection for user (with grace period)."""

    async def close_all(self) -> None
        """Shutdown: close all connections."""

    def add_frontend_connection(self, user_id, connection_id) -> None
        """Register a frontend WS connection for event forwarding."""

    def remove_frontend_connection(self, user_id, connection_id) -> None
        """Unregister. If no frontend connections remain, start grace timer."""
```

**Connection lifecycle:**

1. Frontend WebSocket connects via API Gateway -> `ws_connect` stores in DynamoDB and registers with pool
2. First `req` or `agent_chat` message -> pool creates `GatewayConnection` (opens WS, handshake, starts reader)
3. Subsequent messages reuse the existing connection (no handshake overhead)
4. Gateway broadcasts (`event` type) -> reader forwards to all registered frontend connections via Management API
5. Frontend disconnects -> pool starts 30-second grace timer
6. If no new frontend connections within grace period -> pool closes gateway WS
7. On app shutdown -> `close_all()` tears down everything

**Reconnection:**

If the gateway WebSocket drops unexpectedly, `GatewayConnection` reconnects with exponential backoff (1s, 2s, 4s, max 3 attempts). Any pending RPC Futures are rejected with a retriable error. The frontend can retry.

### Backend: websocket_chat.py Changes

The `ws_message` handler gains `req` message type support:

```python
if msg_type == "req":
    req_id = body.get("id")
    method = body.get("method")
    params = body.get("params", {})

    if not req_id or not method:
        management_api.send_message(connection_id, {
            "type": "res", "id": req_id, "ok": False,
            "error": {"message": "Missing id or method"}
        })
        return Response(status_code=200)

    background_tasks.add_task(
        _process_rpc_background,
        connection_id=connection_id,
        user_id=user_id,
        req_id=req_id,
        method=method,
        params=params,
    )
    return Response(status_code=200)
```

New `_process_rpc_background`:

```python
async def _process_rpc_background(connection_id, user_id, req_id, method, params):
    pool = get_gateway_pool()
    management_api = get_management_api_client()
    try:
        result = await pool.send_rpc(user_id, req_id, method, params)
        management_api.send_message(connection_id, {
            "type": "res", "id": req_id, "ok": True, "payload": result
        })
    except Exception as e:
        management_api.send_message(connection_id, {
            "type": "res", "id": req_id, "ok": False,
            "error": {"message": str(e)}
        })
```

`ws_connect` updated to register frontend connection with pool:

```python
pool = get_gateway_pool()
pool.add_frontend_connection(user_id, connection_id)
```

`ws_disconnect` updated to unregister:

```python
pool = get_gateway_pool()
pool.remove_frontend_connection(user_id, connection_id)
```

**Agent chat refactor (Phase 2):**

`_process_agent_chat_background` currently creates a new `GatewayHttpClient` per message. In a follow-up, this can be refactored to use the pool's persistent connection for chat as well. For the initial implementation, chat continues using `GatewayHttpClient` — the pool handles RPC and events only. This keeps the blast radius small.

### Backend: container_rpc.py Changes

- `GET /status` — unchanged
- `POST /rpc` — kept as deprecated fallback, not removed. Frontend no longer calls it.

### Frontend: GatewayProvider

New file: `src/hooks/useGateway.tsx`

React context provider that owns the single WebSocket connection and exposes it to all hooks.

```typescript
interface GatewayContextValue {
  isConnected: boolean;
  error: string | null;

  // Send OpenClaw req and await res
  sendReq: (method: string, params?: Record<string, unknown>) => Promise<unknown>;

  // Send agent_chat message
  sendChat: (agentName: string, message: string) => void;

  // Subscribe to gateway events
  onEvent: (handler: (event: string, data: unknown) => void) => () => void;

  // Subscribe to chat messages (chunk/done/error/heartbeat)
  onChatMessage: (handler: (msg: ChatIncomingMessage) => void) => () => void;
}
```

**Internals:**

- Owns the WebSocket instance (lazy connect on mount, ping/pong, reconnect with backoff)
- `sendReq(method, params)`: generates UUID, sends `{type: "req", id, method, params}`, stores Promise resolver keyed by `id`, returns Promise that resolves when matching `{type: "res", id}` arrives (30s timeout)
- `sendChat(agentName, message)`: sends `{type: "agent_chat", agent_name, message}` (fire and forget, responses come via `onChatMessage`)
- `onEvent(handler)`: registers callback for `{type: "event"}` messages, returns unsubscribe function
- `onChatMessage(handler)`: registers callback for `chunk`/`done`/`error`/`heartbeat` messages

**Message router (in `onmessage`):**

```typescript
const data = JSON.parse(event.data);
switch (data.type) {
  case "res":     // resolve pending RPC promise by data.id
  case "event":   // dispatch to event subscribers
  case "chunk":   // dispatch to chat subscribers
  case "done":    // dispatch to chat subscribers
  case "error":   // dispatch to chat subscribers (or reject RPC if id matches)
  case "heartbeat": // dispatch to chat subscribers
  case "pong":    // keepalive ack
}
```

### Frontend: useGatewayRpc (replaces useContainerRpc)

New file: `src/hooks/useGatewayRpc.ts`

Drop-in API replacement. Same SWR-based pattern, same return type.

```typescript
export function useGatewayRpc<T>(
  method: string | null,
  params?: Record<string, unknown>,
  config?: SWRConfiguration,
): RpcResult<T> {
  const { sendReq, onEvent } = useGateway();

  const fetcher = useCallback(async (key: string) => {
    const [, m, paramStr] = key.split("|");
    const parsedParams = paramStr ? JSON.parse(paramStr) : undefined;
    return await sendReq(m, parsedParams) as T;
  }, [sendReq]);

  const { data, error, isLoading, mutate } = useSWR<T | undefined>(
    method ? `rpc|${method}|${params ? JSON.stringify(params) : ""}` : null,
    fetcher,
    { revalidateOnFocus: false, dedupingInterval: 10000, ...config },
  );

  // Auto-revalidate when gateway pushes matching event
  useEffect(() => {
    if (!method) return;
    return onEvent((event, _data) => {
      // Revalidate when event name matches method prefix
      // e.g., "health" event revalidates "health" RPC
      if (method.startsWith(event)) mutate();
    });
  }, [method, onEvent, mutate]);

  return { data, error: error as Error | undefined, isLoading, mutate: () => { mutate(); } };
}

export function useGatewayRpcMutation() {
  const { sendReq } = useGateway();

  return useCallback(
    async <T = unknown>(method: string, params?: Record<string, unknown>): Promise<T> => {
      return await sendReq(method, params) as T;
    },
    [sendReq],
  );
}
```

### Frontend: useAgentChat Refactor

`useAgentChat` stops managing its own WebSocket. Instead it uses the shared `GatewayProvider` connection:

- `sendMessage` calls `gateway.sendChat(agentName, message)`
- Chat responses received via `gateway.onChatMessage(handler)` in a useEffect
- All WebSocket lifecycle (connect, ping, reconnect) removed — handled by provider
- Message state, streaming state, error state remain local to the hook

### Frontend: Provider Placement

`GatewayProvider` wraps the chat page layout:

```typescript
// src/app/chat/page.tsx (or ChatLayout)
<GatewayProvider>
  <ChatLayout>...</ChatLayout>
</GatewayProvider>
```

All child components (chat window, control panels) access the shared connection via `useGateway()`.

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `backend/core/gateway/connection_pool.py` | **New** | GatewayConnectionPool + GatewayConnection |
| `backend/core/gateway/__init__.py` | Edit | Add `get_gateway_pool()` singleton |
| `backend/routers/websocket_chat.py` | Edit | Add `req` handler, register/unregister pool connections |
| `backend/routers/container_rpc.py` | Edit | Mark `POST /rpc` as deprecated |
| `frontend/src/hooks/useGateway.tsx` | **New** | GatewayProvider context + useGateway hook |
| `frontend/src/hooks/useGatewayRpc.ts` | **New** | Drop-in replacement for useContainerRpc |
| `frontend/src/hooks/useAgentChat.ts` | Rewrite | Use shared GatewayProvider |
| `frontend/src/hooks/useContainerRpc.ts` | Delete | Replaced by useGatewayRpc |
| `frontend/src/hooks/index.ts` | Edit | Update exports |
| `frontend/src/app/chat/page.tsx` | Edit | Wrap with GatewayProvider |
| All control panel components | Edit | `useContainerRpc` -> `useGatewayRpc` import swap |
| `backend/tests/` | New + Edit | Pool unit tests, updated WS message tests |
| `frontend/src/hooks/__tests__/` | New | useGatewayRpc tests |

## Migration

**Strategy:** Big-bang swap. All control panels switch from `useContainerRpc` to `useGatewayRpc` at once. Agent chat switches to shared provider at the same time.

**Rollback:** The `POST /container/rpc` HTTP endpoint remains functional. If WebSocket RPC has issues, `useGatewayRpc` can be reverted to call HTTP internally (one-line fetcher change) without touching any panel code.

## Implementation Phases

**Phase 1 — Pool + RPC proxy (this work):**
- Backend: GatewayConnectionPool, `req` message handler, connection registration
- Frontend: GatewayProvider, useGatewayRpc, useAgentChat refactor
- All panels migrated to useGatewayRpc

**Phase 2 — Chat through pool (future):**
- Refactor `_process_agent_chat_background` to use pool's persistent WS for chat streaming
- Eliminates GatewayHttpClient entirely
- Single connection handles all gateway communication

**Phase 3 — Real-time subscriptions (future):**
- Frontend subscribes to specific gateway events (channel status changes, health updates)
- Control panels auto-refresh on push instead of polling
- SWR revalidation triggered by gateway events
