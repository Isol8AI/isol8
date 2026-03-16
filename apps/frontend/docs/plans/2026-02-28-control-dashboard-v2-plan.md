# Control Dashboard V2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the control dashboard functional — fix backend scopes, fix all RPC method names, and build rich UI for the 5 core panels.

**Architecture:** Frontend panels call `useContainerRpc(method)` → backend proxy (`POST /container/rpc`) → WebSocket to OpenClaw gateway. The gateway uses protocol v3 with dot-notation methods. Fix the backend handshake scopes to `operator.admin`, fix all wrong method names in panels, and rewrite 5 core panels with proper response handling and rich UI.

**Tech Stack:** Next.js (React), FastAPI, OpenClaw gateway WebSocket RPC

---

## Task 1: Backend — Upgrade handshake scopes to `operator.admin`

**Files:**
- Modify: `backend/routers/container_rpc.py:69`

**Step 1: Change scopes**

In `backend/routers/container_rpc.py` line 69, change:

```python
            "scopes": ["operator.read", "operator.write"],
```

to:

```python
            "scopes": ["operator.admin"],
```

**Step 2: Run backend tests**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend && python -m pytest tests/unit/routers/test_container_rpc.py -v`
Expected: PASS

**Step 3: Commit**

```
feat: upgrade gateway handshake to operator.admin scope
```

---

## Task 2: Fix method names in all non-core panels

**Files:**
- Modify: `frontend/src/components/control/panels/ChannelsPanel.tsx:16`
- Modify: `frontend/src/components/control/panels/InstancesPanel.tsx:16`
- Modify: `frontend/src/components/control/panels/UsagePanel.tsx:21`
- Modify: `frontend/src/components/control/panels/SkillsPanel.tsx:18`
- Modify: `frontend/src/components/control/panels/NodesPanel.tsx:16`
- Modify: `frontend/src/components/control/panels/DebugPanel.tsx:8`

**Step 1: Fix ChannelsPanel**

Change `"channels.list"` to `"channels.status"` on line 16.

**Step 2: Fix InstancesPanel**

Change `"instances.list"` to `"node.list"` on line 16. This panel shows connected nodes/instances.

**Step 3: Fix UsagePanel**

Change `"usage.summary"` to `"usage.cost"` on line 21. The `usage.cost` method returns token counts and cost breakdowns.

**Step 4: Fix SkillsPanel**

Change `"skills.list"` to `"skills.status"` on line 18.

**Step 5: Fix NodesPanel**

Change `"nodes.list"` to `"node.list"` on line 16.

**Step 6: Fix DebugPanel**

Change `"debug.info"` to `"status"` on line 8. The gateway has `status` not `debug.info`.

**Step 7: CronPanel** — Already correct (`"cron.list"` is valid).

**Step 8: Verify no lint errors**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/freebird/frontend && npm run lint`
Expected: PASS

**Step 9: Commit**

```
fix: correct RPC method names for all control panels
```

---

## Task 3: Rewrite OverviewPanel with structured health display

**Files:**
- Modify: `frontend/src/components/control/panels/OverviewPanel.tsx`

**Step 1: Rewrite OverviewPanel**

The `health` method returns a rich object with nested data. Display it with proper sections matching the OpenClaw dashboard: status badge, uptime, version, model info, and key metrics.

Replace the entire file:

```tsx
"use client";

import { Loader2, RefreshCw, Wifi, WifiOff, Clock, Cpu, MessageSquare, Users } from "lucide-react";
import { useContainerRpc } from "@/hooks/useContainerRpc";
import { Button } from "@/components/ui/button";

interface HealthData {
  status?: string;
  uptime?: string | number;
  version?: string;
  ts?: number;
  models?: { primary?: string; fallbacks?: string[] };
  sessions?: { active?: number; total?: number };
  agents?: { count?: number; default?: string };
  cron?: { enabled?: boolean; nextRun?: string };
  [key: string]: unknown;
}

function formatUptime(uptime: string | number | undefined): string {
  if (!uptime) return "—";
  if (typeof uptime === "string") return uptime;
  const hours = Math.floor(uptime / 3600);
  const minutes = Math.floor((uptime % 3600) / 60);
  if (hours > 24) return `${Math.floor(hours / 24)}d ${hours % 24}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

export function OverviewPanel() {
  const { data, error, isLoading, mutate } = useContainerRpc<HealthData>(
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
        No container available.
      </div>
    );
  }

  const status = data.status as string | undefined;
  const isOnline = status === "ok" || status === "running" || status === "healthy";

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Overview</h2>
          <p className="text-xs text-muted-foreground">Gateway status and health snapshot.</p>
        </div>
        <Button variant="ghost" size="sm" onClick={() => mutate()}>
          <RefreshCw className="h-3.5 w-3.5" />
        </Button>
      </div>

      {/* Status Banner */}
      <div className="flex items-center gap-3 rounded-lg border border-border p-4 bg-muted/20">
        {isOnline ? (
          <Wifi className="h-5 w-5 text-green-500" />
        ) : (
          <WifiOff className="h-5 w-5 text-red-500" />
        )}
        <div>
          <div className="text-sm font-semibold">{isOnline ? "Online" : "Offline"}</div>
          <div className="text-xs text-muted-foreground">
            {data.version ? `Version ${data.version}` : ""}
          </div>
        </div>
      </div>

      {/* Metrics Grid */}
      <div className="grid grid-cols-2 gap-3">
        <MetricCard
          icon={Clock}
          label="Uptime"
          value={formatUptime(data.uptime)}
        />
        <MetricCard
          icon={Cpu}
          label="Status"
          value={String(status || "unknown")}
        />
        <MetricCard
          icon={MessageSquare}
          label="Sessions"
          value={data.sessions?.active !== undefined ? String(data.sessions.active) : "—"}
        />
        <MetricCard
          icon={Users}
          label="Agents"
          value={data.agents?.count !== undefined ? String(data.agents.count) : "—"}
        />
      </div>

      {/* Raw Data (collapsed) */}
      <details className="group">
        <summary className="text-xs text-muted-foreground/60 cursor-pointer hover:text-muted-foreground">
          Raw health data
        </summary>
        <pre className="mt-2 text-xs bg-muted/30 rounded-lg p-3 overflow-auto max-h-64">
          {JSON.stringify(data, null, 2)}
        </pre>
      </details>
    </div>
  );
}

function MetricCard({ icon: Icon, label, value }: { icon: typeof Clock; label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border p-3">
      <div className="flex items-center gap-1.5 mb-1">
        <Icon className="h-3 w-3 text-muted-foreground/60" />
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground/60">{label}</span>
      </div>
      <div className="text-sm font-medium">{value}</div>
    </div>
  );
}
```

**Step 2: Verify**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/freebird/frontend && npm run lint`
Expected: PASS

**Step 3: Commit**

```
feat: rewrite OverviewPanel with structured health display
```

---

## Task 4: Rewrite AgentsPanel with file viewer and identity display

**Files:**
- Modify: `frontend/src/components/control/panels/AgentsPanel.tsx`

**Step 1: Rewrite AgentsPanel**

The `agents.list` response is `{ defaultId, mainKey, scope, agents: [{ id, name, identity: { name, emoji } }] }`. The `agent.identity.get` method returns identity details. For file operations we need the agent's workspace files — we'll use `chat.history` to show the last conversation and display agent metadata for now (file editor requires additional gateway methods not in read/write scope).

Replace the entire file:

```tsx
"use client";

import { useState } from "react";
import { Loader2, RefreshCw, Bot, FileText, Wrench, Sparkles, User } from "lucide-react";
import { useContainerRpc } from "@/hooks/useContainerRpc";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type AgentTab = "overview" | "files" | "tools" | "skills";

interface AgentIdentity {
  name?: string;
  theme?: string;
  emoji?: string;
  avatar?: string;
}

interface AgentEntry {
  id: string;
  name?: string;
  identity?: AgentIdentity;
}

interface AgentsListResponse {
  defaultId?: string;
  mainKey?: string;
  scope?: string;
  agents?: AgentEntry[];
}

export function AgentsPanel() {
  const { data: rawData, error, isLoading, mutate } = useContainerRpc<AgentsListResponse>("agents.list");
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

  // Handle both array and object response formats
  const data = rawData as AgentsListResponse | AgentEntry[] | undefined;
  const agents: AgentEntry[] = Array.isArray(data)
    ? data
    : (data as AgentsListResponse)?.agents ?? [];
  const defaultId = !Array.isArray(data) ? (data as AgentsListResponse)?.defaultId : undefined;

  const current = selectedAgent || agents[0]?.id;

  const TABS: { id: AgentTab; label: string; icon: typeof Bot }[] = [
    { id: "overview", label: "Overview", icon: User },
    { id: "files", label: "Files", icon: FileText },
    { id: "tools", label: "Tools", icon: Wrench },
    { id: "skills", label: "Skills", icon: Sparkles },
  ];

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Agents</h2>
          <p className="text-xs text-muted-foreground">{agents.length} configured.</p>
        </div>
        <Button variant="ghost" size="sm" onClick={() => mutate()}>
          <RefreshCw className="h-3.5 w-3.5" />
        </Button>
      </div>

      {/* Agent selector */}
      <div className="flex gap-1 flex-wrap">
        {agents.map((a) => (
          <Button
            key={a.id}
            variant={current === a.id ? "default" : "outline"}
            size="sm"
            onClick={() => setSelectedAgent(a.id)}
          >
            {a.identity?.emoji ? (
              <span className="mr-1">{a.identity.emoji}</span>
            ) : (
              <Bot className="h-3.5 w-3.5 mr-1" />
            )}
            {a.identity?.name || a.name || a.id}
            {a.id === defaultId && (
              <span className="ml-1.5 text-[10px] opacity-60">default</span>
            )}
          </Button>
        ))}
      </div>

      {current && (
        <>
          {/* Sub-tabs */}
          <div className="flex gap-1 border-b border-border">
            {TABS.map((tab) => (
              <button
                key={tab.id}
                className={cn(
                  "flex items-center gap-1 px-3 py-1.5 text-xs font-medium transition-colors",
                  activeTab === tab.id
                    ? "text-foreground border-b-2 border-primary"
                    : "text-muted-foreground hover:text-foreground"
                )}
                onClick={() => setActiveTab(tab.id)}
              >
                <tab.icon className="h-3 w-3" />
                {tab.label}
              </button>
            ))}
          </div>

          {/* Tab content */}
          <AgentTabContent agentId={current} agent={agents.find(a => a.id === current)} tab={activeTab} />
        </>
      )}
    </div>
  );
}

function AgentTabContent({ agentId, agent, tab }: { agentId: string; agent?: AgentEntry; tab: AgentTab }) {
  if (tab === "overview") {
    return <AgentOverviewTab agentId={agentId} agent={agent} />;
  }

  // For files, tools, skills — use agent.identity.get or show raw data
  const methodMap: Record<string, string> = {
    files: "agent.identity.get",
    tools: "skills.status",
    skills: "skills.status",
  };

  const method = methodMap[tab];
  const params = tab === "files" ? { agentId } : undefined;

  return <AgentDataTab method={method} params={params} tab={tab} />;
}

function AgentOverviewTab({ agentId, agent }: { agentId: string; agent?: AgentEntry }) {
  const { data } = useContainerRpc<Record<string, unknown>>(
    "agent.identity.get",
    { agentId },
  );

  const identity = data || agent?.identity;

  return (
    <div className="space-y-4 mt-2">
      <div className="rounded-lg border border-border p-4 space-y-3">
        <h3 className="text-sm font-medium">Identity</h3>
        <div className="grid grid-cols-2 gap-3">
          <InfoRow label="Agent ID" value={agentId} />
          <InfoRow label="Name" value={(identity as Record<string, unknown>)?.name as string || agent?.name || "—"} />
          <InfoRow label="Emoji" value={(identity as Record<string, unknown>)?.emoji as string || "—"} />
          <InfoRow label="Theme" value={(identity as Record<string, unknown>)?.theme as string || "—"} />
        </div>
      </div>

      {/* Raw data */}
      {data && (
        <details className="group">
          <summary className="text-xs text-muted-foreground/60 cursor-pointer hover:text-muted-foreground">
            Raw identity data
          </summary>
          <pre className="mt-2 text-xs bg-muted/30 rounded-lg p-3 overflow-auto max-h-48">
            {JSON.stringify(data, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}

function AgentDataTab({ method, params, tab }: { method: string; params?: Record<string, unknown>; tab: string }) {
  const { data, isLoading } = useContainerRpc<unknown>(method, params);

  if (isLoading) {
    return <Loader2 className="h-4 w-4 animate-spin text-muted-foreground mt-4" />;
  }

  if (!data) {
    return <p className="text-sm text-muted-foreground mt-4">No {tab} data available.</p>;
  }

  return (
    <pre className="text-xs bg-muted/30 rounded-lg p-3 overflow-auto max-h-96 mt-2">
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground/60">{label}</div>
      <div className="text-sm font-medium truncate">{value}</div>
    </div>
  );
}
```

**Step 2: Verify**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/freebird/frontend && npm run lint`
Expected: PASS

**Step 3: Commit**

```
feat: rewrite AgentsPanel with identity display and structured tabs
```

---

## Task 5: Rewrite SessionsPanel with proper response handling

**Files:**
- Modify: `frontend/src/components/control/panels/SessionsPanel.tsx`

**Step 1: Rewrite SessionsPanel**

The `sessions.list` response is `{ sessions: [...] }` not a bare array. Each session has `key`, `agentId`, `model`, `label`, `createdAt`, `updatedAt`, tokens info. Delete uses `sessions.delete` with `{ key }`.

Replace the entire file:

```tsx
"use client";

import { Loader2, RefreshCw, Trash2, MessageSquare } from "lucide-react";
import { useContainerRpc, useContainerRpcMutation } from "@/hooks/useContainerRpc";
import { Button } from "@/components/ui/button";

interface Session {
  key: string;
  agentId?: string;
  model?: string;
  label?: string;
  createdAt?: string;
  updatedAt?: string;
  tokenCount?: { input?: number; output?: number; total?: number };
  [key: string]: unknown;
}

interface SessionsResponse {
  sessions?: Session[];
}

export function SessionsPanel() {
  const { data: rawData, error, isLoading, mutate } = useContainerRpc<SessionsResponse | Session[]>(
    "sessions.list",
    { includeDerivedTitles: true, includeLastMessage: true },
  );
  const callRpc = useContainerRpcMutation();

  const handleDelete = async (key: string) => {
    try {
      await callRpc("sessions.delete", { key });
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

  // Handle both { sessions: [...] } and bare array
  const sessions: Session[] = Array.isArray(rawData)
    ? rawData
    : (rawData as SessionsResponse)?.sessions ?? [];

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Sessions</h2>
          <p className="text-xs text-muted-foreground">{sessions.length} sessions.</p>
        </div>
        <Button variant="ghost" size="sm" onClick={() => mutate()}>
          <RefreshCw className="h-3.5 w-3.5" />
        </Button>
      </div>

      {sessions.length === 0 ? (
        <p className="text-sm text-muted-foreground">No active sessions.</p>
      ) : (
        <div className="space-y-2">
          {sessions.map((s) => (
            <div key={s.key} className="rounded-lg border border-border p-3 space-y-1">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 min-w-0 flex-1">
                  <MessageSquare className="h-3.5 w-3.5 opacity-50 flex-shrink-0" />
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium truncate">
                      {s.label || s.key}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {s.agentId || "—"} · {s.model || "—"}
                    </div>
                  </div>
                </div>
                <Button variant="ghost" size="sm" onClick={() => handleDelete(s.key)}>
                  <Trash2 className="h-3.5 w-3.5 text-muted-foreground hover:text-destructive" />
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

**Step 2: Verify**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/freebird/frontend && npm run lint`
Expected: PASS

**Step 3: Commit**

```
feat: rewrite SessionsPanel with proper response handling and delete
```

---

## Task 6: Rewrite LogsPanel with structured log entries

**Files:**
- Modify: `frontend/src/components/control/panels/LogsPanel.tsx`

**Step 1: Rewrite LogsPanel**

The `logs.tail` response is `{ file, cursor, size, lines: [...], truncated?, reset? }`. Each line is a JSON log entry with timestamp, level, module, and message. Render them with color-coded level badges.

Replace the entire file:

```tsx
"use client";

import { useState } from "react";
import { Loader2, RefreshCw } from "lucide-react";
import { useContainerRpc } from "@/hooks/useContainerRpc";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const LEVELS = ["trace", "debug", "info", "warn", "error", "fatal"] as const;

const LEVEL_COLORS: Record<string, string> = {
  trace: "text-muted-foreground/40",
  debug: "text-muted-foreground",
  info: "text-blue-400",
  warn: "text-yellow-400",
  error: "text-red-400",
  fatal: "text-red-500 font-bold",
};

const LEVEL_BADGE_COLORS: Record<string, string> = {
  trace: "bg-muted/30 text-muted-foreground/60",
  debug: "bg-muted/50 text-muted-foreground",
  info: "bg-blue-500/10 text-blue-400",
  warn: "bg-yellow-500/10 text-yellow-400",
  error: "bg-red-500/10 text-red-400",
  fatal: "bg-red-500/20 text-red-500",
};

interface LogsResponse {
  file?: string;
  cursor?: number;
  size?: number;
  lines?: unknown[];
  truncated?: boolean;
  reset?: boolean;
}

interface LogEntry {
  time?: string;
  date?: string;
  logLevelName?: string;
  level?: string | number;
  name?: string;
  msg?: string;
  message?: string;
  [key: string]: unknown;
}

function parseLogLine(line: unknown): { time: string; level: string; module: string; message: string } {
  if (typeof line === "string") {
    try {
      const parsed = JSON.parse(line) as LogEntry;
      return extractLogFields(parsed);
    } catch {
      return { time: "", level: "info", module: "", message: line };
    }
  }
  if (typeof line === "object" && line !== null) {
    return extractLogFields(line as LogEntry);
  }
  return { time: "", level: "info", module: "", message: String(line) };
}

function extractLogFields(entry: LogEntry): { time: string; level: string; module: string; message: string } {
  const time = entry.time || entry.date || "";
  const timeStr = time ? new Date(time).toLocaleTimeString() : "";

  let level = "info";
  if (entry.logLevelName) level = entry.logLevelName.toLowerCase();
  else if (typeof entry.level === "string") level = entry.level.toLowerCase();
  else if (typeof entry.level === "number") {
    if (entry.level <= 10) level = "trace";
    else if (entry.level <= 20) level = "debug";
    else if (entry.level <= 30) level = "info";
    else if (entry.level <= 40) level = "warn";
    else if (entry.level <= 50) level = "error";
    else level = "fatal";
  }

  const module = entry.name || "";
  const message = entry.msg || entry.message || JSON.stringify(entry);

  return { time: timeStr, level, module, message };
}

export function LogsPanel() {
  const [level, setLevel] = useState<string>("info");
  const { data: rawData, error, isLoading, mutate } = useContainerRpc<LogsResponse | unknown[]>(
    "logs.tail",
    { limit: 200 },
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

  // Handle both { lines: [...] } and bare array
  const rawLines: unknown[] = Array.isArray(rawData)
    ? rawData
    : (rawData as LogsResponse)?.lines ?? [];
  const file = !Array.isArray(rawData) ? (rawData as LogsResponse)?.file : undefined;

  const levelIndex = LEVELS.indexOf(level as typeof LEVELS[number]);
  const allParsed = rawLines.map(parseLogLine);
  const logs = allParsed.filter((entry) => {
    const entryIndex = LEVELS.indexOf(entry.level as typeof LEVELS[number]);
    return entryIndex >= levelIndex;
  });

  return (
    <div className="p-6 space-y-4 flex flex-col h-full">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Logs</h2>
          <p className="text-xs text-muted-foreground">
            {file ? `File: ${file}` : "Gateway file logs."}
          </p>
        </div>
        <Button variant="ghost" size="sm" onClick={() => mutate()}>
          <RefreshCw className="h-3.5 w-3.5" />
        </Button>
      </div>

      <div className="flex gap-1 flex-wrap">
        {LEVELS.map((l) => (
          <button
            key={l}
            className={cn(
              "px-2.5 py-1 text-xs rounded-md transition-colors",
              level === l
                ? LEVEL_BADGE_COLORS[l]
                : "bg-muted/30 text-muted-foreground/40 hover:bg-muted/50 hover:text-muted-foreground"
            )}
            onClick={() => setLevel(l)}
          >
            {l}
          </button>
        ))}
        <span className="text-xs text-muted-foreground/40 self-center ml-2">{logs.length} entries</span>
      </div>

      <div className="flex-1 min-h-0 bg-muted/20 rounded-lg border border-border overflow-auto">
        <div className="p-2 space-y-0.5 font-mono text-xs">
          {logs.length > 0 ? (
            logs.map((entry, i) => (
              <div key={i} className="flex gap-2 px-1 py-0.5 rounded hover:bg-muted/30">
                {entry.time && (
                  <span className="text-muted-foreground/40 flex-shrink-0 w-20">{entry.time}</span>
                )}
                <span className={cn("flex-shrink-0 w-12 text-right", LEVEL_COLORS[entry.level] || "text-muted-foreground")}>
                  {entry.level}
                </span>
                {entry.module && (
                  <span className="text-muted-foreground/60 flex-shrink-0 max-w-24 truncate">{entry.module}</span>
                )}
                <span className="text-foreground/80 break-all">{entry.message}</span>
              </div>
            ))
          ) : (
            <span className="text-muted-foreground p-2">No logs at this level.</span>
          )}
        </div>
      </div>
    </div>
  );
}
```

**Step 2: Verify**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/freebird/frontend && npm run lint`
Expected: PASS

**Step 3: Commit**

```
feat: rewrite LogsPanel with structured log entries and level filtering
```

---

## Task 7: Rewrite ConfigPanel with proper response handling

**Files:**
- Modify: `frontend/src/components/control/panels/ConfigPanel.tsx`

**Step 1: Rewrite ConfigPanel**

The `config.get` response is `{ raw: string, hash: string }` where `raw` is the JSON text of `openclaw.json`. For saving, `config.set` takes `{ raw: string, baseHash?: string }` for optimistic concurrency.

Replace the entire file:

```tsx
"use client";

import { useState } from "react";
import { Loader2, RefreshCw, Save } from "lucide-react";
import { useContainerRpc, useContainerRpcMutation } from "@/hooks/useContainerRpc";
import { Button } from "@/components/ui/button";

interface ConfigResponse {
  raw?: string;
  hash?: string;
}

export function ConfigPanel() {
  const { data: rawData, error, isLoading, mutate } = useContainerRpc<ConfigResponse | Record<string, unknown>>("config.get");
  const callRpc = useContainerRpcMutation();
  const [editing, setEditing] = useState(false);
  const [rawJson, setRawJson] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Handle both { raw, hash } and plain object response
  const configResponse = rawData as ConfigResponse | Record<string, unknown> | undefined;
  const configRaw = typeof (configResponse as ConfigResponse)?.raw === "string"
    ? (configResponse as ConfigResponse).raw!
    : configResponse ? JSON.stringify(configResponse, null, 2) : "";
  const configHash = (configResponse as ConfigResponse)?.hash;

  // Try to pretty-print the raw config
  let displayJson = configRaw;
  try {
    displayJson = JSON.stringify(JSON.parse(configRaw), null, 2);
  } catch {
    // already a string, use as-is
  }

  const startEditing = () => {
    setRawJson(displayJson);
    setEditing(true);
    setSaveError(null);
  };

  const handleSave = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      // Validate JSON
      JSON.parse(rawJson);
      await callRpc("config.set", { raw: rawJson, baseHash: configHash });
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
        <div>
          <h2 className="text-lg font-semibold">Config</h2>
          <p className="text-xs text-muted-foreground">openclaw.json configuration.</p>
        </div>
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
          className="w-full h-[calc(100vh-220px)] bg-muted/30 rounded-lg p-3 text-xs font-mono border border-border focus:outline-none focus:ring-1 focus:ring-primary resize-none"
          value={rawJson}
          onChange={(e) => setRawJson(e.target.value)}
          spellCheck={false}
        />
      ) : (
        <pre className="text-xs bg-muted/30 rounded-lg p-3 overflow-auto max-h-[calc(100vh-220px)] font-mono">
          {displayJson || "No config data."}
        </pre>
      )}
    </div>
  );
}
```

**Step 2: Verify**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/freebird/frontend && npm run lint`
Expected: PASS

**Step 3: Commit**

```
feat: rewrite ConfigPanel with raw/hash response handling and concurrency
```

---

## Task 8: Final verification and push

**Step 1: Run full frontend lint**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/freebird/frontend && npm run lint`
Expected: PASS

**Step 2: Run frontend tests**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/freebird/frontend && npm test`
Expected: PASS

**Step 3: Run backend tests**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend && python -m pytest tests/ -v --timeout=30`
Expected: PASS

**Step 4: Push backend**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend
git push origin main
```

**Step 5: Push frontend**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/freebird/frontend
git push origin main
```

**Step 6: Watch CI runs**

```bash
gh run list --repo Isol8AI/backend --limit 1
gh run list --repo Isol8AI/frontend --limit 1
```

---

## Files Summary

| Action | File |
|--------|------|
| MODIFY | `backend/routers/container_rpc.py:69` (scope change) |
| MODIFY | `frontend/src/components/control/panels/OverviewPanel.tsx` (rewrite) |
| MODIFY | `frontend/src/components/control/panels/AgentsPanel.tsx` (rewrite) |
| MODIFY | `frontend/src/components/control/panels/SessionsPanel.tsx` (rewrite) |
| MODIFY | `frontend/src/components/control/panels/LogsPanel.tsx` (rewrite) |
| MODIFY | `frontend/src/components/control/panels/ConfigPanel.tsx` (rewrite) |
| MODIFY | `frontend/src/components/control/panels/ChannelsPanel.tsx` (method name) |
| MODIFY | `frontend/src/components/control/panels/InstancesPanel.tsx` (method name) |
| MODIFY | `frontend/src/components/control/panels/UsagePanel.tsx` (method name) |
| MODIFY | `frontend/src/components/control/panels/SkillsPanel.tsx` (method name) |
| MODIFY | `frontend/src/components/control/panels/NodesPanel.tsx` (method name) |
| MODIFY | `frontend/src/components/control/panels/DebugPanel.tsx` (method name) |
