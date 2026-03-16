# OpenClaw Control Panel — Design

> Integrate the full OpenClaw gateway dashboard into the Isol8 frontend so users can monitor and control their personal OpenClaw container from the same interface where they chat.

## Context

Each paying Isol8 user gets a dedicated Docker container running `openclaw gateway`. The gateway exposes a WebSocket-RPC API (not REST) that powers the native OpenClaw dashboard — a single-page app served at the gateway's HTTP port.

Today the Isol8 frontend only has chat. Users have no visibility into their container's health, sessions, usage, agent configuration, logs, or connected channels. The native OpenClaw dashboard is not directly accessible because container ports are internal to the EC2 host.

## Goal

Mirror the full OpenClaw gateway dashboard inside the Isol8 frontend. Users should be able to do everything the native dashboard offers: view status, edit agent files, switch models, manage sessions, toggle tools, configure channels, view logs, and more.

## Architecture

### Communication: Backend REST Proxy

The frontend cannot connect directly to user containers (ports are internal to EC2). Instead, the backend acts as a proxy.

```
Browser                    FastAPI Backend              User Container
  |                            |                           |
  | POST /api/v1/container/rpc |                           |
  | { method, params }         |                           |
  |--------------------------->|                           |
  |                            | Look up container port    |
  |                            | + gateway_token from      |
  |                            | cache/DB                  |
  |                            |                           |
  |                            | WS connect to             |
  |                            | ws://127.0.0.1:{port}     |
  |                            | Send JSON-RPC call        |
  |                            |-------------------------->|
  |                            |                           |
  |                            |   JSON-RPC response       |
  |                            |<--------------------------|
  |                            | Close WS                  |
  |                            |                           |
  | JSON response              |                           |
  |<---------------------------|                           |
```

**Why backend proxy (not direct WebSocket):**
- Gateway tokens stay server-side — never exposed to the browser.
- No container ports exposed to the internet.
- Leverages existing container lookup infrastructure (cache + DB fallback).
- Consistent auth via Clerk JWT on all requests.

**Single generic endpoint:** `POST /api/v1/container/rpc` accepts `{ method: string, params?: object }` and forwards to the user's container. This avoids creating 20+ individual REST endpoints. The backend validates that the user has a running container, opens a short-lived WebSocket connection, sends the RPC call, returns the response, and closes the connection.

**Known RPC methods** (discovered via `openclaw gateway call --help` and dashboard observation):
- `health` — gateway health + channel status + agent list + session summaries
- `status` — full status with session token counts, models, channel details
- `agents.list`, `agents.get`, `agents.files`, `agents.tools`, `agents.skills`
- `sessions.list`, `sessions.patch`, `sessions.delete`
- `config.get`, `config.set`
- `logs.tail`
- `cron.list`, `cron.enable`, `cron.disable`
- `skills.list`
- `nodes.list`
- `channels.*`
- `instances.list`

### Frontend: Tabbed Sidebar + Panel Components

The sidebar gains a tab switcher at the top: **Chat** and **Control**.

```
+------------------+--------------------------------+
| [Chat] [Control] |                                |
|                  |                                |
| Control          |     Active Panel Content       |
|   Overview       |     (or Chat when Chat tab)    |
|   Channels       |                                |
|   Instances      |                                |
|   Sessions       |                                |
|   Usage          |                                |
|   Cron Jobs      |                                |
|                  |                                |
| Agent            |                                |
|   Agents         |                                |
|   Skills         |                                |
|   Nodes          |                                |
|                  |                                |
| Settings         |                                |
|   Config         |                                |
|   Debug          |                                |
|   Logs           |                                |
|                  |                                |
+------------------+--------------------------------+
```

When Control tab is active: clicking a section in the sidebar renders that panel's content in the main area (replacing the chat view). When Chat tab is active: current behavior (chat with agent list).

## Sidebar Sections — All 12 Panels

### Control Group

| Panel | Data Source (RPC) | Read | Write |
|-------|-------------------|------|-------|
| **Overview** | `health` | Status, uptime, instance count, session count, cron status | Connect/refresh |
| **Channels** | `health` (channels field), `channels.*` | Channel list (Telegram, iMessage, etc.), running/stopped status, bot info | Start/stop channels |
| **Instances** | `instances.list` | Presence beacons, connected devices | — |
| **Sessions** | `status` (sessions field), `sessions.*` | Session list with token usage, model, thinking/verbose toggles | Patch session settings, delete sessions |
| **Usage** | `usage.*` | Token usage by date range, per-session breakdown, cost estimates | — |
| **Cron Jobs** | `cron.*` | Scheduled tasks, next wake time, enabled/disabled | Enable/disable cron jobs |

### Agent Group

| Panel | Data Source (RPC) | Read | Write |
|-------|-------------------|------|-------|
| **Agents** | `agents.*` | Agent list, identity (name/emoji/model), workspace path, sub-tabs: Overview/Files/Tools/Skills/Channels/Cron | Edit files (SOUL.md, IDENTITY.md, etc.), change model, toggle tools |
| **Skills** | `skills.list` | Built-in + workspace skills, filter/search | — |
| **Nodes** | `nodes.*` | Paired devices, exec approvals, node bindings | Edit exec allowlists, edit bindings |

### Settings Group

| Panel | Data Source (RPC) | Read | Write |
|-------|-------------------|------|-------|
| **Config** | `config.get`, `config.set` | Full openclaw.json as form or raw JSON, categorized (Environment, Agents, Auth, Channels, etc.) | Save config changes |
| **Debug** | `debug.*` | Debug info, diagnostics | — |
| **Logs** | `logs.tail` | Live log stream with level filters (trace/debug/info/warn/error/fatal), search | — |

## Data Fetching

**Shared hook:** `useContainerRpc(method: string, params?: object)` — wraps SWR or a simple fetch to `POST /api/v1/container/rpc`. Returns `{ data, error, isLoading, mutate }`.

**Write operations:** Individual panel components call `POST /api/v1/container/rpc` directly with the appropriate method (e.g., `config.set`, `sessions.patch`).

**Polling for live data:** Overview and Logs panels can poll on an interval (e.g., every 5s for overview, every 2s for logs). No persistent WebSocket from browser needed in v1.

## Error States

- **No container:** Show "Subscribe to access your OpenClaw control panel" (reuse SubscriptionGate).
- **Container offline:** Show "Your OpenClaw container is offline" with status from DB.
- **RPC timeout:** Show inline error with retry button per panel.
- **Auth failure:** Re-fetch gateway token from DB, retry once.

## File Structure

```
src/
  components/
    chat/
      ChatLayout.tsx          # Modified — add tab switcher
    control/
      ControlSidebar.tsx      # Sidebar nav for Control tab
      OverviewPanel.tsx
      ChannelsPanel.tsx
      InstancesPanel.tsx
      SessionsPanel.tsx
      UsagePanel.tsx
      CronJobsPanel.tsx
      AgentsPanel.tsx
      SkillsPanel.tsx
      NodesPanel.tsx
      ConfigPanel.tsx
      DebugPanel.tsx
      LogsPanel.tsx
  hooks/
    useContainerRpc.ts        # Generic RPC hook
  app/
    chat/
      page.tsx                # Modified — route between chat and control panels
```

Backend:
```
routers/
  container_rpc.py            # Single POST /api/v1/container/rpc endpoint
```

## Out of Scope (v1)

- Persistent WebSocket from browser to backend for real-time log streaming (use polling).
- Mobile responsive layout for control panels.
- Keyboard shortcuts for panel navigation.
