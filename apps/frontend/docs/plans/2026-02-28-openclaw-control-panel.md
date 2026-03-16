# OpenClaw Control Panel — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove the 7 Docker-exec-based backend routers and replace them with a single WebSocket-RPC proxy endpoint, then build a tabbed frontend control panel that mirrors the full OpenClaw dashboard.

**Architecture:** The backend gets a single `POST /api/v1/container/rpc` endpoint that opens a short-lived WebSocket connection to the user's OpenClaw gateway container, sends a JSON-RPC call, and returns the response. The frontend adds a Chat/Control tab switcher to the sidebar, with 12 panel components that call the RPC proxy via a shared `useContainerRpc` hook.

**Tech Stack:** Python/FastAPI + `websockets`, Next.js 16 + React 19 + SWR + Tailwind CSS v4 + Radix UI + lucide-react

---

## Phase 1: Backend — Remove Docker Exec Routers

### Task 1: Delete Docker exec routers and their tests

**Files to DELETE:**

Routers:
- `backend/routers/settings.py`
- `backend/routers/files.py`
- `backend/routers/cron.py`
- `backend/routers/skills.py`
- `backend/routers/logs.py`
- `backend/routers/channels.py`

Tests:
- `backend/tests/unit/routers/test_settings.py`
- `backend/tests/unit/routers/test_files.py`
- `backend/tests/unit/routers/test_cron.py`
- `backend/tests/unit/routers/test_skills.py`
- `backend/tests/unit/routers/test_logs.py`
- `backend/tests/unit/routers/test_channels.py`
- `backend/tests/unit/core/test_container_logs.py`

Core:
- `backend/core/containers/config.py` — **DO NOT DELETE**. `write_openclaw_config` is used by `manager.py:193` for provisioning. Only `patch_openclaw_config` was used by `settings.py`. Leave the file as-is.
- `backend/tests/unit/containers/test_config.py` — **KEEP**. Tests `write_openclaw_config` which is still used.

**Step 1: Delete the 6 routers**

```bash
cd backend
rm routers/settings.py routers/files.py routers/cron.py routers/skills.py routers/logs.py routers/channels.py
```

**Step 2: Delete the 7 test files**

```bash
cd backend
rm tests/unit/routers/test_settings.py tests/unit/routers/test_files.py tests/unit/routers/test_cron.py tests/unit/routers/test_skills.py tests/unit/routers/test_logs.py tests/unit/routers/test_channels.py tests/unit/core/test_container_logs.py
```

**Step 3: Commit**

```
refactor: remove Docker exec routers (settings, files, cron, skills, logs, channels)
```

---

### Task 2: Slim down `debug.py` — keep only provision endpoints

The debug router has useful dev-only provision/remove endpoints. Remove the Docker exec endpoints (`get_status`, `get_health`, `get_models`, `get_events`) and keep only `provision_container` and `remove_container`.

**Files:**
- Modify: `backend/routers/debug.py`
- Modify: `backend/tests/unit/routers/test_debug.py`

**Step 1: Rewrite `backend/routers/debug.py`**

```python
"""
Dev-only container provisioning endpoints.

Bypasses Stripe for local testing. Not available in production.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth import AuthContext, get_current_user
from core.config import settings
from core.containers import get_container_manager
from core.containers.manager import ContainerError

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/provision",
    summary="Provision container (dev only)",
    description=(
        "Manually provisions a container for the authenticated user. "
        "Only available in non-production environments for local testing."
    ),
    operation_id="debug_provision_container",
    responses={
        403: {"description": "Not available in production"},
        409: {"description": "Container already running"},
        503: {"description": "Docker not available or provisioning failed"},
    },
)
async def provision_container(auth: AuthContext = Depends(get_current_user)):
    if settings.ENVIRONMENT == "prod":
        raise HTTPException(status_code=403, detail="Not available in production")

    cm = get_container_manager()
    if not cm.available:
        raise HTTPException(status_code=503, detail="Docker not available")

    existing_port = cm.get_container_port(auth.user_id)
    if existing_port:
        return {
            "status": "already_running",
            "port": existing_port,
            "user_id": auth.user_id,
        }

    try:
        info = cm.provision_container(auth.user_id)
        return {
            "status": "provisioned",
            "port": info.port,
            "container_id": info.container_id,
            "user_id": auth.user_id,
        }
    except ContainerError as e:
        logger.error("Dev provision failed for user %s: %s", auth.user_id, e)
        raise HTTPException(status_code=503, detail=str(e))


@router.delete(
    "/provision",
    summary="Remove container (dev only)",
    description="Removes the user's container and optionally its volume. Dev only.",
    operation_id="debug_remove_container",
    responses={
        403: {"description": "Not available in production"},
        404: {"description": "No container found"},
    },
)
async def remove_container(
    keep_volume: bool = Query(True, description="Preserve workspace volume"),
    auth: AuthContext = Depends(get_current_user),
):
    if settings.ENVIRONMENT == "prod":
        raise HTTPException(status_code=403, detail="Not available in production")

    cm = get_container_manager()
    removed = cm.remove_container(auth.user_id, keep_volume=keep_volume)
    if not removed:
        raise HTTPException(status_code=404, detail="No container found")
    return {"status": "removed", "volume_kept": keep_volume}
```

**Step 2: Update `backend/tests/unit/routers/test_debug.py`**

Remove tests for deleted endpoints (`test_get_status`, `test_get_health`, `test_get_models`, `test_get_events`). Keep only provision/remove tests. Read the file first to see what exists, then delete the exec-based test functions.

**Step 3: Run tests**

```bash
cd backend && python -m pytest tests/unit/routers/test_debug.py -v
```

**Step 4: Commit**

```
refactor: slim debug router to provision endpoints only
```

---

### Task 3: Update `main.py` — remove deleted router imports

**Files:**
- Modify: `backend/main.py`

**Step 1: Remove imports and registrations for deleted routers**

In `backend/main.py`, remove:

```python
# DELETE from imports (lines 25-30):
    channels,
    cron,
    files,
    logs,
    skills,
# DELETE this import (line 36):
from routers import settings as settings_router
```

Remove the router registrations (lines 197-216):

```python
# DELETE these lines:
app.include_router(settings_router.router, prefix="/api/v1/settings", tags=["settings"])
app.include_router(files.router, prefix="/api/v1/files", tags=["files"])
app.include_router(cron.router, prefix="/api/v1/cron", tags=["cron"])
app.include_router(skills.router, prefix="/api/v1/skills", tags=["skills"])
app.include_router(logs.router, prefix="/api/v1/logs", tags=["logs"])
app.include_router(channels.router, prefix="/api/v1/channels", tags=["channels"])
```

Remove the OpenAPI tag entries for deleted routers from `openapi_tags` list:

```python
# DELETE these tag dicts:
    {"name": "settings", ...},
    {"name": "files", ...},
    {"name": "cron", ...},
    {"name": "skills", ...},
    {"name": "debug", ...},  # UPDATE description to "Dev-only container provisioning."
    {"name": "logs", ...},
    {"name": "channels", ...},
```

Keep the `debug` tag but update its description to `"Dev-only container provisioning."`.

**Step 2: Run all tests to verify nothing breaks**

```bash
cd backend && python -m pytest tests/ -v
```

Expected: All remaining tests pass. Contract tests may need updating if they reference deleted endpoints.

**Step 3: Fix any contract test failures**

Check `tests/contract/test_api_contracts.py` and `tests/unit/routers/test_remaining_openapi.py` for references to deleted routers. Remove or update as needed.

**Step 4: Commit**

```
refactor: remove deleted router imports and registrations from main.py
```

---

### Task 4: Add `websockets` dependency

**Files:**
- Modify: `backend/requirements.txt`

**Step 1: Add websockets**

Add to `backend/requirements.txt` after the Docker SDK line:

```
# WebSocket client for OpenClaw gateway RPC proxy
websockets>=12.0
```

**Step 2: Install**

```bash
cd backend && pip install websockets>=12.0
```

**Step 3: Commit**

```
chore: add websockets dependency for RPC proxy
```

---

### Task 5: Create `POST /api/v1/container/rpc` endpoint

This is the core backend addition. A single endpoint that proxies JSON-RPC calls to the user's OpenClaw gateway container via short-lived WebSocket connections.

**Files:**
- Create: `backend/routers/container_rpc.py`
- Create: `backend/tests/unit/routers/test_container_rpc.py`

**Step 1: Write the failing test**

Create `backend/tests/unit/routers/test_container_rpc.py`:

```python
"""Tests for the container RPC proxy endpoint."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.container_rpc import router


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/container")
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def mock_auth():
    """Patch get_current_user to return a fake AuthContext."""
    auth = MagicMock()
    auth.user_id = "user_test123"
    with patch("routers.container_rpc.get_current_user", return_value=auth):
        yield auth


@pytest.fixture
def mock_container_manager():
    cm = MagicMock()
    with patch("routers.container_rpc.get_container_manager", return_value=cm):
        yield cm


class TestContainerRpcEndpoint:
    def test_rpc_returns_404_when_no_container(self, client, mock_auth, mock_container_manager):
        mock_container_manager.get_container_info.return_value = None

        response = client.post(
            "/api/v1/container/rpc",
            json={"method": "health"},
        )
        assert response.status_code == 404
        assert "container" in response.json()["detail"].lower()

    def test_rpc_returns_404_when_container_not_running(self, client, mock_auth, mock_container_manager):
        info = MagicMock()
        info.status = "stopped"
        mock_container_manager.get_container_info.return_value = info

        response = client.post(
            "/api/v1/container/rpc",
            json={"method": "health"},
        )
        assert response.status_code == 404

    def test_rpc_validates_method_required(self, client, mock_auth, mock_container_manager):
        response = client.post(
            "/api/v1/container/rpc",
            json={},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_rpc_forwards_to_gateway(self, mock_auth, mock_container_manager):
        """Unit test: verify the proxy function opens WS and forwards."""
        from routers.container_rpc import _call_gateway_rpc

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(return_value=json.dumps({"status": "ok", "uptime": 3600}))

        with patch("routers.container_rpc.ws_connect", return_value=mock_ws):
            mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
            mock_ws.__aexit__ = AsyncMock(return_value=False)

            result = await _call_gateway_rpc(
                port=19001,
                token="test-token",
                method="health",
                params={},
            )

        assert result == {"status": "ok", "uptime": 3600}
        mock_ws.send.assert_called_once()
        sent = json.loads(mock_ws.send.call_args[0][0])
        assert sent["method"] == "health"

    @pytest.mark.asyncio
    async def test_rpc_handles_ws_connection_error(self, mock_auth, mock_container_manager):
        from routers.container_rpc import _call_gateway_rpc

        with patch("routers.container_rpc.ws_connect", side_effect=ConnectionRefusedError("refused")):
            with pytest.raises(Exception):
                await _call_gateway_rpc(port=19001, token="t", method="health")
```

**Step 2: Run tests to verify they fail**

```bash
cd backend && python -m pytest tests/unit/routers/test_container_rpc.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'routers.container_rpc'`

**Step 3: Create `backend/routers/container_rpc.py`**

```python
"""
Generic RPC proxy to user's OpenClaw gateway container.

Single endpoint: POST /rpc accepts { method, params } and forwards
to the user's container via short-lived WebSocket connection.
Gateway tokens stay server-side — never exposed to the browser.
"""

import json
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from websockets import connect as ws_connect

from core.auth import AuthContext, get_current_user
from core.containers import get_container_manager

logger = logging.getLogger(__name__)

router = APIRouter()

_WS_TIMEOUT = 30  # seconds


class RpcRequest(BaseModel):
    method: str = Field(..., description="RPC method name (e.g. 'health', 'agents.list')")
    params: Optional[Dict[str, Any]] = Field(default=None, description="Optional method parameters")


class RpcResponse(BaseModel):
    result: Any


async def _call_gateway_rpc(
    port: int,
    token: str,
    method: str,
    params: Optional[Dict[str, Any]] = None,
) -> Any:
    """Open a short-lived WebSocket to the gateway, send RPC call, return response."""
    uri = f"ws://127.0.0.1:{port}"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    message = json.dumps({"method": method, "params": params or {}})

    async with ws_connect(uri, additional_headers=headers, open_timeout=_WS_TIMEOUT, close_timeout=5) as ws:
        await ws.send(message)
        raw = await ws.recv()

    return json.loads(raw)


@router.post(
    "/rpc",
    summary="Proxy RPC call to user's OpenClaw container",
    description=(
        "Forwards a JSON-RPC call to the user's dedicated OpenClaw container. "
        "Opens a short-lived WebSocket connection, sends the method call, "
        "and returns the response. Gateway tokens are never exposed to the browser."
    ),
    operation_id="container_rpc",
    responses={
        404: {"description": "No running container for this user"},
        502: {"description": "Gateway connection or RPC call failed"},
    },
)
async def container_rpc(
    body: RpcRequest,
    auth: AuthContext = Depends(get_current_user),
):
    cm = get_container_manager()
    info = cm.get_container_info(auth.user_id)

    if not info or info.status != "running":
        raise HTTPException(
            status_code=404,
            detail="No running container. Subscribe to access the control panel.",
        )

    try:
        result = await _call_gateway_rpc(
            port=info.port,
            token=info.gateway_token,
            method=body.method,
            params=body.params,
        )
    except ConnectionRefusedError:
        logger.error("Gateway refused connection for user %s on port %d", auth.user_id, info.port)
        raise HTTPException(status_code=502, detail="Container gateway is not responding")
    except TimeoutError:
        logger.error("Gateway timeout for user %s on port %d", auth.user_id, info.port)
        raise HTTPException(status_code=502, detail="Container gateway timed out")
    except json.JSONDecodeError as e:
        logger.error("Invalid JSON from gateway for user %s: %s", auth.user_id, e)
        raise HTTPException(status_code=502, detail="Invalid response from container gateway")
    except Exception as e:
        logger.error("RPC call failed for user %s: %s", auth.user_id, e)
        raise HTTPException(status_code=502, detail="Gateway RPC call failed")

    return {"result": result}
```

**Step 4: Run tests**

```bash
cd backend && python -m pytest tests/unit/routers/test_container_rpc.py -v
```

Expected: PASS

**Step 5: Commit**

```
feat: add POST /api/v1/container/rpc WebSocket-RPC proxy endpoint
```

---

### Task 6: Register RPC router in `main.py`

**Files:**
- Modify: `backend/main.py`

**Step 1: Add import**

Add to the imports block in `main.py`:

```python
from routers import container_rpc
```

**Step 2: Add OpenAPI tag**

Add to `openapi_tags` list:

```python
{
    "name": "container",
    "description": "OpenClaw container RPC proxy for the control panel.",
},
```

**Step 3: Register the router**

Add after the billing router registration:

```python
# Container RPC proxy (OpenClaw control panel)
app.include_router(container_rpc.router, prefix="/api/v1/container", tags=["container"])
```

**Step 4: Run full backend tests**

```bash
cd backend && python -m pytest tests/ -v
```

Expected: All tests pass.

**Step 5: Commit**

```
feat: register container RPC router in main.py
```

---

## Phase 2: Frontend — Foundation

### Task 7: Add `delete` method to `useApi` and create `useContainerRpc` hook

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Create: `frontend/src/hooks/useContainerRpc.ts`

**Step 1: Add `delete` method to `useApi`**

In `frontend/src/lib/api.ts`, add to the `ApiMethods` interface:

```typescript
del: (endpoint: string) => Promise<unknown>;
```

And add to the returned object:

```typescript
del(endpoint: string): Promise<unknown> {
  return authenticatedFetch(endpoint, { method: "DELETE" });
},
```

**Step 2: Create `frontend/src/hooks/useContainerRpc.ts`**

```typescript
"use client";

import { useCallback } from "react";
import useSWR, { SWRConfiguration } from "swr";
import { useAuth } from "@clerk/nextjs";
import { BACKEND_URL } from "@/lib/api";

interface RpcResult<T = unknown> {
  data: T | undefined;
  error: Error | undefined;
  isLoading: boolean;
  mutate: () => void;
}

/**
 * Hook for read-only RPC calls (auto-fetched via SWR).
 *
 * Usage:
 *   const { data, isLoading } = useContainerRpc<HealthData>("health");
 *   const { data } = useContainerRpc<AgentList>("agents.list");
 */
export function useContainerRpc<T = unknown>(
  method: string | null,
  params?: Record<string, unknown>,
  config?: SWRConfiguration,
): RpcResult<T> {
  const { getToken, isSignedIn } = useAuth();

  const fetcher = useCallback(
    async (key: string) => {
      const token = await getToken();
      if (!token) throw new Error("No auth token");

      const [, method, paramStr] = key.split("|");
      const parsedParams = paramStr ? JSON.parse(paramStr) : undefined;

      const res = await fetch(`${BACKEND_URL}/container/rpc`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ method, params: parsedParams }),
      });

      if (res.status === 404) return undefined;
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "RPC call failed");
      }

      const { result } = await res.json();
      return result as T;
    },
    [getToken],
  );

  // SWR key encodes method + params for cache deduplication
  const swrKey =
    isSignedIn && method
      ? `rpc|${method}|${params ? JSON.stringify(params) : ""}`
      : null;

  const { data, error, isLoading, mutate } = useSWR<T>(swrKey, fetcher, {
    revalidateOnFocus: false,
    dedupingInterval: 10000,
    ...config,
  });

  return {
    data,
    error: error as Error | undefined,
    isLoading,
    mutate: () => { mutate(); },
  };
}

/**
 * Hook for write RPC calls (imperative, not auto-fetched).
 *
 * Usage:
 *   const callRpc = useContainerRpcMutation();
 *   await callRpc("config.set", { key: "value" });
 */
export function useContainerRpcMutation() {
  const { getToken } = useAuth();

  return useCallback(
    async <T = unknown>(method: string, params?: Record<string, unknown>): Promise<T> => {
      const token = await getToken();
      if (!token) throw new Error("No auth token");

      const res = await fetch(`${BACKEND_URL}/container/rpc`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ method, params }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "RPC call failed");
      }

      const { result } = await res.json();
      return result as T;
    },
    [getToken],
  );
}
```

**Step 3: Commit**

```
feat: add useContainerRpc hook and delete method to useApi
```

---

### Task 8: Add tabbed layout to ChatLayout

Modify the sidebar to have Chat/Control tabs. When Control is active, render a sidebar navigation with panel sections instead of the agent list.

**Files:**
- Modify: `frontend/src/components/chat/ChatLayout.tsx`
- Modify: `frontend/src/app/chat/page.tsx`

**Step 1: Update ChatLayout to accept a `view` prop**

```typescript
// ChatLayout.tsx — new interface
interface ChatLayoutProps {
  children: React.ReactNode;
  activeView: "chat" | "control";
  onViewChange: (view: "chat" | "control") => void;
  activePanel?: string;
  onPanelChange?: (panel: string) => void;
}
```

**Step 2: Add tab switcher to the sidebar header**

Replace the `"Agents"` header div with a tab bar:

```tsx
<div className="flex border-b border-border">
  <button
    className={cn(
      "flex-1 px-3 py-2 text-xs font-medium uppercase tracking-wider transition-colors",
      activeView === "chat"
        ? "text-foreground border-b-2 border-primary"
        : "text-muted-foreground hover:text-foreground"
    )}
    onClick={() => onViewChange("chat")}
  >
    Chat
  </button>
  <button
    className={cn(
      "flex-1 px-3 py-2 text-xs font-medium uppercase tracking-wider transition-colors",
      activeView === "control"
        ? "text-foreground border-b-2 border-primary"
        : "text-muted-foreground hover:text-foreground"
    )}
    onClick={() => onViewChange("control")}
  >
    Control
  </button>
</div>
```

**Step 3: Conditionally render sidebar content**

When `activeView === "chat"`: render the current agent list (New Agent button + agent buttons).
When `activeView === "control"`: render the `ControlSidebar` (created in Task 9).

```tsx
{activeView === "chat" ? (
  <>
    {/* Existing agent list */}
    <div className="px-3 py-2">
      <Button ... disabled>New Agent</Button>
    </div>
    <ScrollArea ...>
      {agents.map(...)}
    </ScrollArea>
  </>
) : (
  <ControlSidebar activePanel={activePanel} onPanelChange={onPanelChange} />
)}
```

**Step 4: Update ChatPage to manage view state**

In `frontend/src/app/chat/page.tsx`:

```tsx
export default function ChatPage() {
  const [selectedAgent, setSelectedAgent] = useState<string>("main");
  const [activeView, setActiveView] = useState<"chat" | "control">("chat");
  const [activePanel, setActivePanel] = useState<string>("overview");

  // ... existing selectAgent listener ...

  return (
    <ChatLayout
      activeView={activeView}
      onViewChange={setActiveView}
      activePanel={activePanel}
      onPanelChange={(panel) => setActivePanel(panel)}
    >
      {activeView === "chat" ? (
        <AgentChatWindow agentName={selectedAgent} />
      ) : (
        <ControlPanelRouter panel={activePanel} />
      )}
    </ChatLayout>
  );
}
```

**Step 5: Commit**

```
feat: add Chat/Control tab switcher to sidebar
```

---

### Task 9: Create ControlSidebar and ControlPanelRouter

**Files:**
- Create: `frontend/src/components/control/ControlSidebar.tsx`
- Create: `frontend/src/components/control/ControlPanelRouter.tsx`

**Step 1: Create `ControlSidebar.tsx`**

```tsx
"use client";

import {
  Activity, Radio, Monitor, MessageSquare, BarChart3, Clock,
  Bot, Sparkles, Network,
  Settings, Bug, ScrollText,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { ScrollArea } from "@/components/ui/scroll-area";

interface ControlSidebarProps {
  activePanel?: string;
  onPanelChange?: (panel: string) => void;
}

const SECTIONS = [
  {
    label: "Control",
    items: [
      { id: "overview", label: "Overview", icon: Activity },
      { id: "channels", label: "Channels", icon: Radio },
      { id: "instances", label: "Instances", icon: Monitor },
      { id: "sessions", label: "Sessions", icon: MessageSquare },
      { id: "usage", label: "Usage", icon: BarChart3 },
      { id: "cron", label: "Cron Jobs", icon: Clock },
    ],
  },
  {
    label: "Agent",
    items: [
      { id: "agents", label: "Agents", icon: Bot },
      { id: "skills", label: "Skills", icon: Sparkles },
      { id: "nodes", label: "Nodes", icon: Network },
    ],
  },
  {
    label: "Settings",
    items: [
      { id: "config", label: "Config", icon: Settings },
      { id: "debug", label: "Debug", icon: Bug },
      { id: "logs", label: "Logs", icon: ScrollText },
    ],
  },
];

export function ControlSidebar({ activePanel = "overview", onPanelChange }: ControlSidebarProps) {
  return (
    <ScrollArea className="flex-1">
      <div className="py-2">
        {SECTIONS.map((section) => (
          <div key={section.label} className="mb-2">
            <div className="px-3 py-1 text-[10px] font-medium text-muted-foreground/60 uppercase tracking-wider">
              {section.label}
            </div>
            {section.items.map((item) => (
              <button
                key={item.id}
                className={cn(
                  "w-full flex items-center gap-2 px-3 py-1.5 text-sm transition-colors",
                  activePanel === item.id
                    ? "bg-accent text-accent-foreground"
                    : "text-muted-foreground hover:text-foreground hover:bg-accent/50"
                )}
                onClick={() => onPanelChange?.(item.id)}
              >
                <item.icon className="h-3.5 w-3.5 flex-shrink-0 opacity-70" />
                <span className="truncate">{item.label}</span>
              </button>
            ))}
          </div>
        ))}
      </div>
    </ScrollArea>
  );
}
```

**Step 2: Create `ControlPanelRouter.tsx`**

```tsx
"use client";

import { OverviewPanel } from "./panels/OverviewPanel";
import { ChannelsPanel } from "./panels/ChannelsPanel";
import { InstancesPanel } from "./panels/InstancesPanel";
import { SessionsPanel } from "./panels/SessionsPanel";
import { UsagePanel } from "./panels/UsagePanel";
import { CronPanel } from "./panels/CronPanel";
import { AgentsPanel } from "./panels/AgentsPanel";
import { SkillsPanel } from "./panels/SkillsPanel";
import { NodesPanel } from "./panels/NodesPanel";
import { ConfigPanel } from "./panels/ConfigPanel";
import { DebugPanel } from "./panels/DebugPanel";
import { LogsPanel } from "./panels/LogsPanel";

interface ControlPanelRouterProps {
  panel: string;
}

const PANELS: Record<string, React.ComponentType> = {
  overview: OverviewPanel,
  channels: ChannelsPanel,
  instances: InstancesPanel,
  sessions: SessionsPanel,
  usage: UsagePanel,
  cron: CronPanel,
  agents: AgentsPanel,
  skills: SkillsPanel,
  nodes: NodesPanel,
  config: ConfigPanel,
  debug: DebugPanel,
  logs: LogsPanel,
};

export function ControlPanelRouter({ panel }: ControlPanelRouterProps) {
  const Panel = PANELS[panel] || PANELS.overview;
  return <Panel />;
}
```

**Step 3: Create stub panel files**

Create `frontend/src/components/control/panels/` directory. For each of the 12 panels, create a minimal stub:

```tsx
// Example: frontend/src/components/control/panels/OverviewPanel.tsx
"use client";

export function OverviewPanel() {
  return <div className="p-6 text-muted-foreground">Overview panel — coming soon</div>;
}
```

Create stubs for: `OverviewPanel.tsx`, `ChannelsPanel.tsx`, `InstancesPanel.tsx`, `SessionsPanel.tsx`, `UsagePanel.tsx`, `CronPanel.tsx`, `AgentsPanel.tsx`, `SkillsPanel.tsx`, `NodesPanel.tsx`, `ConfigPanel.tsx`, `DebugPanel.tsx`, `LogsPanel.tsx`.

**Step 4: Verify the app builds**

```bash
cd frontend && npm run build
```

**Step 5: Commit**

```
feat: add ControlSidebar, ControlPanelRouter, and 12 stub panels
```

---

## Phase 3: Frontend — Panel Implementations

Each panel follows the same pattern: call `useContainerRpc` with the appropriate method, render loading/error states, display data.

### Task 10: OverviewPanel

**Files:**
- Modify: `frontend/src/components/control/panels/OverviewPanel.tsx`

**Step 1: Implement**

```tsx
"use client";

import { Loader2, RefreshCw, Wifi, WifiOff } from "lucide-react";
import { useContainerRpc } from "@/hooks/useContainerRpc";
import { Button } from "@/components/ui/button";

export function OverviewPanel() {
  const { data, error, isLoading, mutate } = useContainerRpc<Record<string, unknown>>(
    "health",
    undefined,
    { refreshInterval: 10000 },
  );

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 space-y-3">
        <p className="text-sm text-destructive">Failed to fetch status: {error.message}</p>
        <Button variant="outline" size="sm" onClick={() => mutate()}>
          <RefreshCw className="h-3.5 w-3.5 mr-1.5" /> Retry
        </Button>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        No container available. Subscribe to access the control panel.
      </div>
    );
  }

  const status = (data as Record<string, unknown>).status as string | undefined;
  const isOnline = status === "ok" || status === "running";

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Overview</h2>
        <Button variant="ghost" size="sm" onClick={() => mutate()}>
          <RefreshCw className="h-3.5 w-3.5" />
        </Button>
      </div>

      <div className="flex items-center gap-2">
        {isOnline ? (
          <Wifi className="h-4 w-4 text-green-500" />
        ) : (
          <WifiOff className="h-4 w-4 text-red-500" />
        )}
        <span className="text-sm font-medium">{isOnline ? "Online" : "Offline"}</span>
      </div>

      <div className="grid grid-cols-2 gap-4">
        {Object.entries(data).map(([key, value]) => (
          <div key={key} className="rounded-lg border border-border p-3">
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground/60 mb-1">
              {key.replace(/([A-Z])/g, " $1").replace(/_/g, " ")}
            </div>
            <div className="text-sm font-medium truncate">
              {typeof value === "object" ? JSON.stringify(value) : String(value ?? "—")}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
```

**Step 2: Commit**

```
feat: implement OverviewPanel with health polling
```

---

### Task 11: SessionsPanel

**Files:**
- Modify: `frontend/src/components/control/panels/SessionsPanel.tsx`

**Step 1: Implement**

```tsx
"use client";

import { Loader2, RefreshCw, Trash2 } from "lucide-react";
import { useContainerRpc, useContainerRpcMutation } from "@/hooks/useContainerRpc";
import { Button } from "@/components/ui/button";

interface Session {
  id: string;
  agent?: string;
  model?: string;
  tokens?: { input?: number; output?: number; total?: number };
  updated?: string;
  [key: string]: unknown;
}

export function SessionsPanel() {
  const { data, error, isLoading, mutate } = useContainerRpc<Session[]>("sessions.list");
  const callRpc = useContainerRpcMutation();

  const handleDelete = async (id: string) => {
    try {
      await callRpc("sessions.delete", { id });
      mutate();
    } catch (err) {
      console.error("Failed to delete session:", err);
    }
  };

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 space-y-3">
        <p className="text-sm text-destructive">{error.message}</p>
        <Button variant="outline" size="sm" onClick={() => mutate()}>
          <RefreshCw className="h-3.5 w-3.5 mr-1.5" /> Retry
        </Button>
      </div>
    );
  }

  const sessions = Array.isArray(data) ? data : [];

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Sessions</h2>
        <Button variant="ghost" size="sm" onClick={() => mutate()}>
          <RefreshCw className="h-3.5 w-3.5" />
        </Button>
      </div>

      {sessions.length === 0 ? (
        <p className="text-sm text-muted-foreground">No active sessions.</p>
      ) : (
        <div className="space-y-2">
          {sessions.map((s) => (
            <div key={s.id} className="flex items-center justify-between rounded-lg border border-border p-3">
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium truncate">{s.agent || "unknown"}</div>
                <div className="text-xs text-muted-foreground">
                  {s.model || "—"} · {s.tokens?.total ?? 0} tokens
                </div>
              </div>
              <Button variant="ghost" size="sm" onClick={() => handleDelete(s.id)}>
                <Trash2 className="h-3.5 w-3.5 text-muted-foreground" />
              </Button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

**Step 2: Commit**

```
feat: implement SessionsPanel with delete
```

---

### Task 12: ChannelsPanel

**Files:**
- Modify: `frontend/src/components/control/panels/ChannelsPanel.tsx`

**Step 1: Implement**

```tsx
"use client";

import { Loader2, RefreshCw, Radio } from "lucide-react";
import { useContainerRpc, useContainerRpcMutation } from "@/hooks/useContainerRpc";
import { Button } from "@/components/ui/button";

interface Channel {
  name: string;
  enabled?: boolean;
  running?: boolean;
  type?: string;
  [key: string]: unknown;
}

export function ChannelsPanel() {
  const { data, error, isLoading, mutate } = useContainerRpc<Channel[]>("channels.list");
  const callRpc = useContainerRpcMutation();

  const handleToggle = async (name: string, currentlyEnabled: boolean) => {
    const method = currentlyEnabled ? "channels.disable" : "channels.enable";
    try {
      await callRpc(method, { name });
      mutate();
    } catch (err) {
      console.error("Failed to toggle channel:", err);
    }
  };

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 space-y-3">
        <p className="text-sm text-destructive">{error.message}</p>
        <Button variant="outline" size="sm" onClick={() => mutate()}>
          <RefreshCw className="h-3.5 w-3.5 mr-1.5" /> Retry
        </Button>
      </div>
    );
  }

  const channels = Array.isArray(data) ? data : [];

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Channels</h2>
        <Button variant="ghost" size="sm" onClick={() => mutate()}>
          <RefreshCw className="h-3.5 w-3.5" />
        </Button>
      </div>

      {channels.length === 0 ? (
        <p className="text-sm text-muted-foreground">No channels configured.</p>
      ) : (
        <div className="space-y-2">
          {channels.map((ch) => (
            <div key={ch.name} className="flex items-center justify-between rounded-lg border border-border p-3">
              <div className="flex items-center gap-2">
                <Radio className="h-3.5 w-3.5 opacity-50" />
                <div>
                  <div className="text-sm font-medium">{ch.name}</div>
                  <div className="text-xs text-muted-foreground">{ch.type || "—"}</div>
                </div>
              </div>
              <Button
                variant={ch.enabled ? "outline" : "default"}
                size="sm"
                onClick={() => handleToggle(ch.name, !!ch.enabled)}
              >
                {ch.enabled ? "Disable" : "Enable"}
              </Button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

**Step 2: Commit**

```
feat: implement ChannelsPanel with enable/disable
```

---

### Task 13: CronPanel, SkillsPanel, NodesPanel, InstancesPanel, UsagePanel

These are all list-display panels with similar structure. Implement them all in one task.

**Files:**
- Modify: `frontend/src/components/control/panels/CronPanel.tsx`
- Modify: `frontend/src/components/control/panels/SkillsPanel.tsx`
- Modify: `frontend/src/components/control/panels/NodesPanel.tsx`
- Modify: `frontend/src/components/control/panels/InstancesPanel.tsx`
- Modify: `frontend/src/components/control/panels/UsagePanel.tsx`

**Step 1: Implement each panel**

Each follows the same pattern as OverviewPanel — `useContainerRpc` with the appropriate method, render the list. Use these RPC methods:

| Panel | RPC method | Write methods |
|-------|-----------|---------------|
| CronPanel | `cron.list` | `cron.enable`, `cron.disable` |
| SkillsPanel | `skills.list` | — |
| NodesPanel | `nodes.list` | — |
| InstancesPanel | `instances.list` | — |
| UsagePanel | `usage.summary` | — |

For CronPanel, add enable/disable toggle buttons (same pattern as ChannelsPanel).

For SkillsPanel, add a search/filter input.

For NodesPanel and InstancesPanel, render simple card lists.

For UsagePanel, render token counts and cost breakdowns.

**Step 2: Verify build**

```bash
cd frontend && npm run build
```

**Step 3: Commit**

```
feat: implement CronPanel, SkillsPanel, NodesPanel, InstancesPanel, UsagePanel
```

---

### Task 14: AgentsPanel

The richest panel — shows agent list with sub-sections for identity, files, tools, and skills.

**Files:**
- Modify: `frontend/src/components/control/panels/AgentsPanel.tsx`

**Step 1: Implement**

```tsx
"use client";

import { useState } from "react";
import { Loader2, RefreshCw, Bot, FileText, Wrench, Sparkles } from "lucide-react";
import { useContainerRpc } from "@/hooks/useContainerRpc";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type AgentTab = "overview" | "files" | "tools" | "skills";

export function AgentsPanel() {
  const { data, error, isLoading, mutate } = useContainerRpc<Record<string, unknown>[]>("agents.list");
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<AgentTab>("overview");

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 space-y-3">
        <p className="text-sm text-destructive">{error.message}</p>
        <Button variant="outline" size="sm" onClick={() => mutate()}>
          <RefreshCw className="h-3.5 w-3.5 mr-1.5" /> Retry
        </Button>
      </div>
    );
  }

  const agents = Array.isArray(data) ? data : [];
  const current = selectedAgent || (agents[0] as Record<string, unknown>)?.name as string | undefined;

  const TABS: { id: AgentTab; label: string; icon: typeof Bot }[] = [
    { id: "overview", label: "Overview", icon: Bot },
    { id: "files", label: "Files", icon: FileText },
    { id: "tools", label: "Tools", icon: Wrench },
    { id: "skills", label: "Skills", icon: Sparkles },
  ];

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Agents</h2>
        <Button variant="ghost" size="sm" onClick={() => mutate()}>
          <RefreshCw className="h-3.5 w-3.5" />
        </Button>
      </div>

      {/* Agent selector */}
      <div className="flex gap-1 flex-wrap">
        {agents.map((a) => {
          const name = (a as Record<string, unknown>).name as string;
          return (
            <Button
              key={name}
              variant={current === name ? "default" : "outline"}
              size="sm"
              onClick={() => setSelectedAgent(name)}
            >
              <Bot className="h-3.5 w-3.5 mr-1" />
              {name}
            </Button>
          );
        })}
      </div>

      {current && (
        <>
          {/* Sub-tabs */}
          <div className="flex gap-1 border-b border-border">
            {TABS.map((tab) => (
              <button
                key={tab.id}
                className={cn(
                  "px-3 py-1.5 text-xs font-medium transition-colors",
                  activeTab === tab.id
                    ? "text-foreground border-b-2 border-primary"
                    : "text-muted-foreground hover:text-foreground"
                )}
                onClick={() => setActiveTab(tab.id)}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Tab content */}
          <AgentTabContent agent={current} tab={activeTab} />
        </>
      )}
    </div>
  );
}

function AgentTabContent({ agent, tab }: { agent: string; tab: AgentTab }) {
  const methodMap: Record<AgentTab, string> = {
    overview: "agents.get",
    files: "agents.files",
    tools: "agents.tools",
    skills: "agents.skills",
  };

  const { data, isLoading } = useContainerRpc<unknown>(
    methodMap[tab],
    { agent },
  );

  if (isLoading) {
    return <Loader2 className="h-4 w-4 animate-spin text-muted-foreground mt-4" />;
  }

  if (!data) {
    return <p className="text-sm text-muted-foreground mt-4">No data.</p>;
  }

  return (
    <pre className="text-xs bg-muted/30 rounded-lg p-3 overflow-auto max-h-96 mt-2">
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}
```

**Step 2: Commit**

```
feat: implement AgentsPanel with sub-tabs
```

---

### Task 15: ConfigPanel

JSON config viewer/editor.

**Files:**
- Modify: `frontend/src/components/control/panels/ConfigPanel.tsx`

**Step 1: Implement**

```tsx
"use client";

import { useState } from "react";
import { Loader2, RefreshCw, Save } from "lucide-react";
import { useContainerRpc, useContainerRpcMutation } from "@/hooks/useContainerRpc";
import { Button } from "@/components/ui/button";

export function ConfigPanel() {
  const { data, error, isLoading, mutate } = useContainerRpc<Record<string, unknown>>("config.get");
  const callRpc = useContainerRpcMutation();
  const [editing, setEditing] = useState(false);
  const [rawJson, setRawJson] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const startEditing = () => {
    setRawJson(JSON.stringify(data, null, 2));
    setEditing(true);
    setSaveError(null);
  };

  const handleSave = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      const parsed = JSON.parse(rawJson);
      await callRpc("config.set", parsed);
      setEditing(false);
      mutate();
    } catch (err) {
      setSaveError(err instanceof SyntaxError ? "Invalid JSON" : String(err));
    } finally {
      setSaving(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 space-y-3">
        <p className="text-sm text-destructive">{error.message}</p>
        <Button variant="outline" size="sm" onClick={() => mutate()}>
          <RefreshCw className="h-3.5 w-3.5 mr-1.5" /> Retry
        </Button>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Config</h2>
        <div className="flex gap-2">
          {editing ? (
            <>
              <Button variant="ghost" size="sm" onClick={() => setEditing(false)}>
                Cancel
              </Button>
              <Button size="sm" onClick={handleSave} disabled={saving}>
                {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5 mr-1" />}
                Save
              </Button>
            </>
          ) : (
            <>
              <Button variant="ghost" size="sm" onClick={() => mutate()}>
                <RefreshCw className="h-3.5 w-3.5" />
              </Button>
              <Button variant="outline" size="sm" onClick={startEditing}>
                Edit
              </Button>
            </>
          )}
        </div>
      </div>

      {saveError && <p className="text-sm text-destructive">{saveError}</p>}

      {editing ? (
        <textarea
          className="w-full h-96 bg-muted/30 rounded-lg p-3 text-xs font-mono border border-border focus:outline-none focus:ring-1 focus:ring-primary resize-none"
          value={rawJson}
          onChange={(e) => setRawJson(e.target.value)}
          spellCheck={false}
        />
      ) : (
        <pre className="text-xs bg-muted/30 rounded-lg p-3 overflow-auto max-h-[calc(100vh-200px)]">
          {data ? JSON.stringify(data, null, 2) : "No config data."}
        </pre>
      )}
    </div>
  );
}
```

**Step 2: Commit**

```
feat: implement ConfigPanel with JSON editor
```

---

### Task 16: LogsPanel and DebugPanel

**Files:**
- Modify: `frontend/src/components/control/panels/LogsPanel.tsx`
- Modify: `frontend/src/components/control/panels/DebugPanel.tsx`

**Step 1: Implement LogsPanel**

```tsx
"use client";

import { useState } from "react";
import { Loader2, RefreshCw } from "lucide-react";
import { useContainerRpc } from "@/hooks/useContainerRpc";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const LEVELS = ["trace", "debug", "info", "warn", "error", "fatal"] as const;

export function LogsPanel() {
  const [level, setLevel] = useState<string>("info");
  const { data, error, isLoading, mutate } = useContainerRpc<unknown>(
    "logs.tail",
    { level, limit: 200 },
    { refreshInterval: 5000 },
  );

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 space-y-3">
        <p className="text-sm text-destructive">{error.message}</p>
        <Button variant="outline" size="sm" onClick={() => mutate()}>
          <RefreshCw className="h-3.5 w-3.5 mr-1.5" /> Retry
        </Button>
      </div>
    );
  }

  const logs = Array.isArray(data) ? data : typeof data === "string" ? data.split("\n") : [];

  return (
    <div className="p-6 space-y-4 flex flex-col h-full">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Logs</h2>
        <Button variant="ghost" size="sm" onClick={() => mutate()}>
          <RefreshCw className="h-3.5 w-3.5" />
        </Button>
      </div>

      <div className="flex gap-1 flex-wrap">
        {LEVELS.map((l) => (
          <button
            key={l}
            className={cn(
              "px-2 py-0.5 text-xs rounded-md transition-colors",
              level === l
                ? "bg-primary text-primary-foreground"
                : "bg-muted/50 text-muted-foreground hover:bg-muted"
            )}
            onClick={() => setLevel(l)}
          >
            {l}
          </button>
        ))}
      </div>

      <pre className="flex-1 text-xs bg-muted/30 rounded-lg p-3 overflow-auto font-mono leading-relaxed min-h-0">
        {logs.length > 0 ? (
          logs.map((line, i) => (
            <div key={i} className="hover:bg-muted/20">
              {typeof line === "string" ? line : JSON.stringify(line)}
            </div>
          ))
        ) : (
          <span className="text-muted-foreground">No logs available.</span>
        )}
      </pre>
    </div>
  );
}
```

**Step 2: Implement DebugPanel**

```tsx
"use client";

import { Loader2, RefreshCw } from "lucide-react";
import { useContainerRpc } from "@/hooks/useContainerRpc";
import { Button } from "@/components/ui/button";

export function DebugPanel() {
  const { data, error, isLoading, mutate } = useContainerRpc<unknown>("debug.info");

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 space-y-3">
        <p className="text-sm text-destructive">{error.message}</p>
        <Button variant="outline" size="sm" onClick={() => mutate()}>
          <RefreshCw className="h-3.5 w-3.5 mr-1.5" /> Retry
        </Button>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Debug</h2>
        <Button variant="ghost" size="sm" onClick={() => mutate()}>
          <RefreshCw className="h-3.5 w-3.5" />
        </Button>
      </div>

      <pre className="text-xs bg-muted/30 rounded-lg p-3 overflow-auto max-h-[calc(100vh-200px)]">
        {data ? JSON.stringify(data, null, 2) : "No debug data."}
      </pre>
    </div>
  );
}
```

**Step 3: Commit**

```
feat: implement LogsPanel and DebugPanel
```

---

### Task 17: Final build + full test suite

**Step 1: Run frontend build**

```bash
cd frontend && npm run build
```

**Step 2: Run frontend tests**

```bash
cd frontend && npm test
```

**Step 3: Run backend tests**

```bash
cd backend && python -m pytest tests/ -v
```

**Step 4: Verify no stale imports remain**

```bash
grep -r "routers.settings\|routers.files\|routers.cron\|routers.skills\|routers.logs\|routers.channels" backend/ --include="*.py"
grep -r "exec_command\|get_container_logs" backend/routers/ --include="*.py"
```

Both should return zero results.

**Step 5: Fix any failures, then commit**

```
chore: verify full test suite passes after control panel implementation
```

---

## Files Summary

| Action | File |
|--------|------|
| DELETE | `backend/routers/settings.py` |
| DELETE | `backend/routers/files.py` |
| DELETE | `backend/routers/cron.py` |
| DELETE | `backend/routers/skills.py` |
| DELETE | `backend/routers/logs.py` |
| DELETE | `backend/routers/channels.py` |
| DELETE | `backend/tests/unit/routers/test_settings.py` |
| DELETE | `backend/tests/unit/routers/test_files.py` |
| DELETE | `backend/tests/unit/routers/test_cron.py` |
| DELETE | `backend/tests/unit/routers/test_skills.py` |
| DELETE | `backend/tests/unit/routers/test_logs.py` |
| DELETE | `backend/tests/unit/routers/test_channels.py` |
| DELETE | `backend/tests/unit/core/test_container_logs.py` |
| MODIFY | `backend/routers/debug.py` |
| MODIFY | `backend/tests/unit/routers/test_debug.py` |
| MODIFY | `backend/main.py` |
| MODIFY | `backend/requirements.txt` |
| CREATE | `backend/routers/container_rpc.py` |
| CREATE | `backend/tests/unit/routers/test_container_rpc.py` |
| MODIFY | `frontend/src/lib/api.ts` |
| CREATE | `frontend/src/hooks/useContainerRpc.ts` |
| MODIFY | `frontend/src/components/chat/ChatLayout.tsx` |
| MODIFY | `frontend/src/app/chat/page.tsx` |
| CREATE | `frontend/src/components/control/ControlSidebar.tsx` |
| CREATE | `frontend/src/components/control/ControlPanelRouter.tsx` |
| CREATE | `frontend/src/components/control/panels/OverviewPanel.tsx` |
| CREATE | `frontend/src/components/control/panels/ChannelsPanel.tsx` |
| CREATE | `frontend/src/components/control/panels/InstancesPanel.tsx` |
| CREATE | `frontend/src/components/control/panels/SessionsPanel.tsx` |
| CREATE | `frontend/src/components/control/panels/UsagePanel.tsx` |
| CREATE | `frontend/src/components/control/panels/CronPanel.tsx` |
| CREATE | `frontend/src/components/control/panels/AgentsPanel.tsx` |
| CREATE | `frontend/src/components/control/panels/SkillsPanel.tsx` |
| CREATE | `frontend/src/components/control/panels/NodesPanel.tsx` |
| CREATE | `frontend/src/components/control/panels/ConfigPanel.tsx` |
| CREATE | `frontend/src/components/control/panels/DebugPanel.tsx` |
| CREATE | `frontend/src/components/control/panels/LogsPanel.tsx` |

## Verification

1. `cd backend && python -m pytest tests/ -v` — all backend tests pass
2. `cd frontend && npm run build` — frontend builds without errors
3. `cd frontend && npm test` — frontend tests pass
4. `grep -r "exec_command\|get_container_logs" backend/routers/ --include="*.py"` — zero results (no Docker exec in routers)
5. `grep -r "routers.settings\|routers.files\|routers.cron\|routers.skills\|routers.logs\|routers.channels" backend/ --include="*.py"` — zero results
