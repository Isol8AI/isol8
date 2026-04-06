# Paperclip Integration Design

## Overview

Add [Paperclip](https://github.com/paperclipai/paperclip) as an optional feature for Pro and Enterprise users. Paperclip is an AI agent team orchestration platform that sits on top of OpenClaw — where OpenClaw is the individual agent runtime, Paperclip manages teams of agents with org charts, task management, scheduled execution, budgets, and governance.

Each user gets their own personal Paperclip instance running as an ECS sidecar alongside their OpenClaw container. Isol8 provides a custom React UI that calls Paperclip's REST API through a backend proxy.

## Architecture

```
ECS Task (pro/enterprise, Paperclip enabled)
+-- Container 1: OpenClaw          :18789  (existing)
+-- Container 2: Paperclip         :3100   (sidecar)
    +-- Shared network namespace (localhost between containers)
    +-- Shared EFS volume
    +-- Paperclip -> OpenClaw: ws://localhost:18789
    +-- Embedded Postgres on EFS
    +-- authenticated mode, private exposure

Backend (ECS) -> container_ip:3100 (direct HTTP, same as control-ui proxy pattern)
Frontend -> Backend /api/v1/paperclip/proxy/* -> container_ip:3100/api/*
```

### Networking

Paperclip runs in `authenticated` mode with `private` exposure, binding to `0.0.0.0:3100`. This is required because the backend needs to reach Paperclip over the container IP (not loopback). `local_trusted` mode enforces loopback-only binding and cannot be overridden.

The backend reaches Paperclip the same way the control-ui proxy reaches OpenClaw — resolve container IP via `ecs.resolve_running_container()`, then direct HTTP with `httpx`.

### Auth

- `BETTER_AUTH_SECRET`: One static random string stored in Secrets Manager, shared across all Paperclip instances. Used internally by Better Auth to sign session cookies. Not per-user, not a credential.
- Board API Key: Per-user bearer token (`pcp_board_<hex>`) created via Paperclip's API during provisioning. Stored in DynamoDB alongside container metadata. Backend sends it as `Authorization: Bearer pcp_board_...` on all proxy calls.

### Database

Paperclip uses its embedded Postgres mode. Data lives on the user's EFS volume. No external Postgres or additional infrastructure needed.

## Tier Gating

| Tier | Paperclip available | Toggle |
|------|-------------------|--------|
| free | No | -- |
| starter | No | -- |
| pro | Yes | User enables/disables |
| enterprise | Yes | User enables/disables |

Enabling/disabling Paperclip swaps the ECS task definition (with/without sidecar container) and forces a new deployment.

## Phase 1: Infrastructure (CDK)

### Task Definition

The sidecar container is additive to the tier's base resources:

| Tier | Base CPU/Mem | With Paperclip CPU/Mem |
|------|-------------|----------------------|
| pro | 1024/2048 | 1536/3072 |
| enterprise | 2048/4096 | 2560/5120 |

Paperclip container definition:
- Image: pinned version tag (e.g., `ghcr.io/paperclipai/paperclip:v0.X.Y`), managed via `PAPERCLIP_IMAGE` config setting
- CPU: 512 (soft limit)
- Memory: 1024 (soft limit)
- Port: 3100
- Essential: false (Paperclip crash does not kill OpenClaw)
- Mount: same EFS volume as OpenClaw
- Env vars:
  - `PAPERCLIP_DEPLOYMENT_MODE=authenticated`
  - `PAPERCLIP_DEPLOYMENT_EXPOSURE=private`
  - `BETTER_AUTH_SECRET=<from Secrets Manager>`
  - `HOST=0.0.0.0`
  - `PORT=3100`

### Security Group

Allow inbound TCP 3100 from the backend's security group (one rule addition).

### CloudWatch

New log group: `/isol8/${env}/paperclip`

## Phase 2: Backend

### Config (`config.py`)

New settings:
- `PAPERCLIP_IMAGE: str` — pinned Paperclip Docker image (like `OPENCLAW_IMAGE`)
- `PAPERCLIP_PORT: int = 3100`
- `BETTER_AUTH_SECRET: str` — from Secrets Manager

Add to `TIER_CONFIG`:
- `"paperclip_enabled": False` for free and starter
- `"paperclip_enabled": True` for pro and enterprise

### EcsManager Changes

**Toggle on (enable Paperclip):**
1. Register new task definition revision with Paperclip sidecar container added
2. Force new ECS deployment
3. Wait for Paperclip healthy (`GET http://{container_ip}:3100/api/health`)
4. Call Paperclip API to create board user + Board API Key
5. Store Board API Key in DynamoDB alongside container metadata

**Toggle off (disable Paperclip):**
1. Register new task definition revision without sidecar container
2. Force new ECS deployment
3. Remove Board API Key from DynamoDB

Paperclip data persists on EFS — re-enabling restores previous state.

### Paperclip API Router (`paperclip_api.py`)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/v1/paperclip/status` | Health check + enabled state |
| `POST /api/v1/paperclip/enable` | Toggle on (pro/enterprise only, triggers task def swap) |
| `POST /api/v1/paperclip/disable` | Toggle off (triggers task def swap) |
| `ANY /api/v1/paperclip/proxy/{path:path}` | Proxy to `http://{container_ip}:3100/api/{path}` with Board API Key |

All endpoints authenticated via `get_current_user`. Enable/disable check tier eligibility. Proxy checks Paperclip is enabled and healthy.

The proxy uses `httpx.AsyncClient` following the same pattern as `control_ui_proxy.py`.

### Router Registration (`main.py`)

```python
from routers import paperclip_api
app.include_router(paperclip_api.router, prefix="/api/v1/paperclip", tags=["paperclip"])
```

## Phase 3: Frontend

### Approach: Adapt Paperclip's UI Source

Paperclip's UI is built with the same stack as Isol8 (React + shadcn/ui + Tailwind + lucide icons). Rather than building views from scratch, we reference Paperclip's component source and adapt each page:

1. Copy layout/structure from Paperclip's components
2. Swap API calls to go through our `/api/v1/paperclip/proxy/*` endpoint
3. Style to match Isol8's theme (colors, spacing)
4. Remove what we don't need (see below)

### What We Remove (per-user simplifications)

- **Company Rail** — each user has one company, no workspace switcher needed
- **Auth pages** — Isol8 handles auth via Clerk
- **Instance settings** — backend controls Paperclip config
- **Board claim / CLI auth / invite pages** — backend manages access
- **Multi-company features** — company prefix routing simplified

### Route: `/teams`

Separate page from the control dashboard, linked from a card in the control dashboard's overview panel. Protected by Clerk middleware (same as `/chat`).

### Layout

```
Isol8 Header (existing, with nav back to /chat)
+-- Teams Sidebar (240px, Paperclip nav items)
+-- Main Content (flex-1, Paperclip pages restyled to Isol8 theme)
```

### Teams Sidebar Navigation

Adapted from Paperclip's sidebar, minus company rail and instance settings:

- **Dashboard** (LayoutDashboard) — metric cards + charts
- **Inbox** (Inbox) — notifications, failed runs
- **Work section:**
  - Issues (CircleDot) — task list + kanban
  - Routines (Repeat) — cron-scheduled recurring tasks
  - Goals (Target) — hierarchical goal tree
- **Projects section:** collapsible list of projects
- **Agents section:** collapsible list with live status indicators
- **Company section:**
  - Org Chart (Network) — SVG org chart canvas
  - Skills (Boxes) — skill management
  - Costs (DollarSign) — cost analytics + charts
  - Activity (History) — activity feed
  - Settings (Settings) — company settings

### Pages (all under `/teams/*`)

| Route | Source Component | Description |
|-------|-----------------|-------------|
| `/teams` | Dashboard | Metric cards (agents, tasks, spend, approvals) + charts (run activity, issues by priority/status, success rate) + recent activity + recent tasks |
| `/teams/inbox` | Inbox | Tabbed inbox (mine/recent/unread/all) |
| `/teams/issues` | Issues | Issue list with filters, kanban board view |
| `/teams/issues/:id` | IssueDetail | Single issue detail |
| `/teams/routines` | Routines | Routine list with schedule editor |
| `/teams/routines/:id` | RoutineDetail | Routine detail |
| `/teams/goals` | Goals | Goal tree view |
| `/teams/goals/:id` | GoalDetail | Goal detail |
| `/teams/projects` | Projects | Project list |
| `/teams/projects/:id` | ProjectDetail | Project detail (tabs: overview/issues/workspaces/configuration/budget) |
| `/teams/agents` | Agents | Agent list with filter tabs (all/active/paused/error), list + org tree views |
| `/teams/agents/new` | NewAgent | New agent form, pre-filled with OpenClaw gateway adapter config |
| `/teams/agents/:id` | AgentDetail | Agent detail (tabs: overview/runs/configuration/skills/permissions/keys/budget) |
| `/teams/agents/:id/runs/:runId` | AgentDetail | Run transcript |
| `/teams/approvals` | Approvals | Approval cards (pending/all) |
| `/teams/costs` | Costs | Cost analytics, charts, provider breakdowns |
| `/teams/activity` | Activity | Activity feed, filterable by entity type |
| `/teams/org` | OrgChart | SVG canvas with pan/zoom, agent cards in tree layout |
| `/teams/skills` | Skills | Skill file tree browser |
| `/teams/settings` | CompanySettings | Company settings form |

### API Hook (`usePaperclip.ts`)

SWR-based hooks wrapping calls to `/api/v1/paperclip/*`:
- `usePaperclipStatus()` — GET `/paperclip/status`
- `usePaperclipApi<T>(path)` — GET `/paperclip/proxy/{path}`
- `usePaperclipMutation(path)` — POST/PUT/DELETE `/paperclip/proxy/{path}`

Uses `useApi()` from `src/lib/api.ts` for authenticated requests.

### Not-Enabled State

If the user is on pro/enterprise but hasn't enabled Paperclip, `/teams` shows a CTA page explaining the feature with an "Enable Teams" button (calls POST `/paperclip/enable`). If the user is on free/starter, the page shows an upgrade CTA.

### Control Dashboard Link

Add a "Teams" card to the Overview panel in the control dashboard that links to `/teams`. Gated by tier (pro/enterprise only).

### Agent Creation Pre-fill

When creating a new agent via `/teams/agents/new`, the OpenClaw gateway adapter config auto-fills:
- `adapter: openclaw_gateway`
- `url: ws://localhost:18789`
- Auth via OpenClaw's trusted-proxy (no token needed)

## Phase 4: Lifecycle & Integration

### Paperclip to OpenClaw Connection

Paperclip agents use the OpenClaw gateway adapter with config:
- `url: ws://localhost:18789` (sidecar shared network namespace)
- Auth via OpenClaw's trusted-proxy mode (same task = trusted source IP)

When hiring an agent in the UI, the adapter config auto-fills with the localhost URL.

### Container Lifecycle

- Paperclip sidecar `essential: false` — Paperclip crash does not affect OpenClaw
- Task restart → both containers restart together
- `delete_user_service` → both containers destroyed (same task)

### Tier Changes

- starter → pro: Paperclip becomes available in UI, not auto-enabled
- pro → starter: if Paperclip enabled, auto-disable (swap task def, remove sidecar)
- Paperclip data persists on EFS regardless of toggle/tier state

### Health

- Backend checks `/api/health` when proxying
- Frontend shows connection status in Teams panel
- Paperclip unhealthy does not affect OpenClaw or chat

## Open Questions

1. **Paperclip image version**: What is the latest stable version tag on `ghcr.io/paperclipai/paperclip`?
2. **Board API Key creation flow**: Exact API sequence to programmatically create a board user and API key in authenticated mode (may need to use the bootstrap/claim flow on first start).
3. **EFS path for Paperclip data**: Confirm embedded Postgres works reliably on NFS — may need testing.

## Risks

1. **Embedded Postgres on EFS/NFS** — database performance over network filesystem may be slow. Monitor and consider external Postgres if issues arise.
2. **Paperclip API stability** — custom UI depends on Paperclip's REST API. Breaking changes in updates require frontend fixes. Pinned image version mitigates this.
3. **Sidecar resource contention** — Paperclip's 512 CPU soft limit may contend with OpenClaw under heavy load. Monitor and adjust limits.
4. **Board API Key provisioning timing** — Paperclip must be fully healthy before the backend can create the key. Need robust retry/wait logic during provisioning.
