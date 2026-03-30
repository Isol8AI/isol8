# Unified Health & Recovery UX — Phase 1

**Issue:** [Isol8AI/isol8#47](https://github.com/Isol8AI/isol8/issues/47)
**Date:** 2026-03-30
**Scope:** Unified health model, persistent status indicator, "Fix it" button, hybrid push+poll status updates.
**Out of scope (Phase 2):** Status detail panel, event timeline, event log persistence.

---

## Problem

Container/gateway status is scattered across 4 components (`ConnectionStatusBar`, `ProvisioningStepper`, `OverviewPanel`, `DebugPanel`), each polling at different rates and sometimes disagreeing. Action buttons are unclear ("Update Gateway" restarts a process, not installs an update). When things break, users don't know what happened or what to do.

## Design

### 1. Health State Model

Five states derived from three signals: container record (DynamoDB), gateway health RPC, and WebSocket connection state.

| State | Container | Gateway | WS | Indicator | Button |
|-------|-----------|---------|-----|-----------|--------|
| `HEALTHY` | running | ok | connected | Green dot | Hidden |
| `STARTING` | provisioning | — | — | Yellow dot (pulsing) | "Cancel" |
| `RECOVERING` | running | — | reconnecting | Yellow dot (pulsing) | Spinner, no action |
| `GATEWAY_DOWN` | running | unresponsive | disconnected | Red dot | "Restart Gateway" |
| `CONTAINER_DOWN` | stopped/error | — | disconnected | Red dot | "Restart Agent" |

**Derivation rules (first match wins):**

1. Container status is `provisioning` → `STARTING`
2. Container status is `stopped` or `error` → `CONTAINER_DOWN`
3. WS is reconnecting (attempt count < 10) → `RECOVERING`
4. WS is disconnected AND container is `running` AND gateway health RPC fails or times out → `GATEWAY_DOWN`
5. Otherwise → `HEALTHY`

Each state carries a `reason` string for display in the tooltip. Examples:
- `CONTAINER_DOWN`: "Container stopped — out of memory" (from `last_error` field)
- `GATEWAY_DOWN`: "Gateway not responding — health check timed out"
- `RECOVERING`: "Reconnecting... attempt 3 of 10"
- `STARTING`: "Container provisioning — waiting for ECS task"

### 2. Persistent Health Indicator (Sidebar)

A colored dot rendered at the top of the `Sidebar` component, always visible (no auto-hide).

**Placement:** Below the "Agents" header, above the agent list. Full-width row with dot + label + optional button.

**Visual states:**
- **Green dot** — `HEALTHY`. Label: "Connected". No button.
- **Yellow pulsing dot** — `STARTING` or `RECOVERING`. Label: state reason. Button: spinner (RECOVERING) or "Cancel" (STARTING).
- **Red dot** — `GATEWAY_DOWN` or `CONTAINER_DOWN`. Label: state reason. Button: "Restart Gateway" or "Restart Agent".

**Tooltip on hover:** Full reason string (e.g., "Container stopped — out of memory at 14:23 UTC").

**Replaces:** `ConnectionStatusBar.tsx` is removed entirely. The auto-hide behavior (connected → hide after 3s) is eliminated — users always see current status.

### 3. "Fix It" Button

#### Backend: `POST /api/v1/container/recover`

Single endpoint that inspects current state and takes the appropriate recovery action.

**Logic:**

```
1. Load container record for authenticated user (owner_id)
2. If no container → 404
3. Acquire per-owner recovery lock (DynamoDB conditional write or in-memory lock)
   - If lock held → return {action: "already_recovering", state: current_state}
4. Inspect state:
   a. Container status is "stopped" or "error"
      → Full re-provision: stop ECS service → cleanup → create new task → wait for running
      → Return {action: "reprovision"}
   b. Container status is "running" but gateway health fails
      → Restart gateway: attempt update.run RPC first (2s timeout) — this restarts the gateway process
      → If RPC fails (gateway truly unresponsive): force new ECS deployment (stop task → ECS reschedules)
      → Return {action: "gateway_restart"}
   c. Container is healthy
      → Return {action: "none", message: "System is healthy"}
5. Release lock (or let it expire after 60s TTL)
```

**Response schema:**
```json
{
  "action": "reprovision" | "gateway_restart" | "none" | "already_recovering",
  "state": "CONTAINER_DOWN" | "GATEWAY_DOWN" | "HEALTHY" | ...,
  "reason": "Container stopped — out of memory"
}
```

**Idempotency:** Per-owner lock prevents concurrent recovery. Repeated calls while recovery is in progress return `already_recovering`. The lock expires after 60s as a safety valve.

#### Frontend behavior based on response:

- `gateway_restart` → Show spinner on button for 5s, then re-evaluate health state via poll/push.
- `reprovision` → Transition chat area to `ProvisioningStepper` (reuse existing component). Stepper handles the multi-step provisioning flow as it does during initial onboarding.
- `none` → Brief toast: "System is healthy — no action needed."
- `already_recovering` → Brief toast: "Recovery already in progress."

### 4. Status Updates (Hybrid Push + Poll)

Three signal sources merged by `useSystemHealth`:

| Source | Frequency | What it provides | When active |
|--------|-----------|-----------------|-------------|
| REST poll | 10s | Container record (status, substatus, last_error) | Always |
| WS health RPC | 5s | Gateway health (ok, uptime, agents, sessions) | When WS connected |
| WS push events | Immediate | Critical state transitions | When WS connected |

**Push events:** Backend emits `status_change` events via the Management API when it detects:
- Container state transitions (provisioning → running, running → stopped, etc.)
- Gateway connection established or lost (in `connection_pool.py`)

**Push event schema:**
```json
{
  "type": "status_change",
  "state": "CONTAINER_DOWN",
  "reason": "ECS task stopped — OutOfMemoryError",
  "timestamp": "2026-03-30T14:23:00Z"
}
```

**Fallback:** When WS is disconnected, only REST poll is active. The 10s interval is sufficient since the user already knows something is wrong (red indicator), and the poll confirms when recovery completes.

### 5. Container Model Changes

Add two fields to the DynamoDB `containers` table:

| Field | Type | Purpose |
|-------|------|---------|
| `last_error` | `str \| null` | Human-readable error reason (e.g., "OutOfMemoryError", "ECS task failed to start") |
| `last_error_at` | `str \| null` | ISO timestamp of last error |

These are populated by:
- The ECS task stop callback (when we detect a task stopped)
- The `recover` endpoint (when it detects a failure state)
- The idle scaler (when it intentionally stops a container, sets reason to "Scaled to zero — idle timeout")

The `GET /container/status` endpoint returns these fields in its response so the frontend can display them in the tooltip.

### 6. ProvisioningStepper Changes

Currently `ProvisioningStepper` only renders during initial onboarding. It needs to also render when triggered by recovery.

**Change:** Accept an optional `trigger` prop:
- `trigger="onboarding"` (default) — current behavior, full 4-step flow
- `trigger="recovery"` — skip billing step (user already has a plan), start from container provisioning

The `ChatLayout` or `AgentChatWindow` switches to the stepper view when `useSystemHealth` state is `STARTING` and the recovery action was `reprovision`.

### 7. OverviewPanel Changes

Remove the 4 confusing action buttons ("Reload Config", "Update Gateway", "Probe Channels", "Health Check").

Replace with:
- A health summary card that mirrors the sidebar indicator (state + reason + "Fix it" button if applicable)
- Container info card (unchanged: service name, plan, region, created)
- Gateway snapshot card (unchanged: uptime, tick interval, agents, sessions)

The individual RPC actions (config.apply, channels.status) remain available via the existing RPC infrastructure but are no longer exposed as unlabeled buttons. Advanced users can use the Debug panel or the backend API directly.

---

## Files Changed

### New files
| File | Purpose |
|------|---------|
| `apps/frontend/src/hooks/useSystemHealth.ts` | Unified health state hook — merges REST poll + WS health RPC + WS push into `{state, reason, action}` |
| `apps/frontend/src/components/chat/HealthIndicator.tsx` | Sidebar health dot + label + "Fix it" button |

### Modified files
| File | Change |
|------|--------|
| `apps/backend/routers/container_rpc.py` | Add `POST /recover` endpoint with state inspection, per-owner lock, recovery dispatch |
| `apps/backend/core/gateway/connection_pool.py` | Emit `status_change` WS events on gateway connect/disconnect |
| `apps/backend/core/containers/config_store.py` | Add `last_error`, `last_error_at` fields, populate on state transitions |
| `apps/frontend/src/components/chat/Sidebar.tsx` | Render `HealthIndicator` at top of sidebar |
| `apps/frontend/src/components/chat/ChatLayout.tsx` | Remove `ConnectionStatusBar` import/render |
| `apps/frontend/src/components/chat/ProvisioningStepper.tsx` | Add `trigger` prop, skip billing step for recovery flow |
| `apps/frontend/src/components/control/panels/OverviewPanel.tsx` | Remove 4 action buttons, add health summary card |

### Removed files
| File | Reason |
|------|--------|
| `apps/frontend/src/components/chat/ConnectionStatusBar.tsx` | Replaced by `HealthIndicator` |

---

## Edge Cases

**WS down + container running:** REST poll returns `status: "running"` but we can't reach the gateway. After 3 failed polls without WS, derive `GATEWAY_DOWN`. The "Restart Gateway" action uses the REST endpoint (not WS RPC) since WS is unavailable.

**Recovery lock expiry:** If the backend crashes mid-recovery, the 60s TTL lock releases automatically. Next recovery call re-evaluates state and retries.

**Free tier scale-to-zero:** When idle scaler stops a container, set `last_error: "Scaled to zero — idle timeout"`. State becomes `CONTAINER_DOWN` but the reason makes it clear this is expected. On next chat message, auto-reprovision triggers as it does today.

**Concurrent tab/sessions:** Multiple browser tabs share the same owner_id. Recovery lock prevents duplicate actions. Push events notify all connected tabs simultaneously.

**ProvisioningStepper already visible:** If the stepper is already showing (initial onboarding), the recovery response `reprovision` is a no-op on the frontend — stepper is already handling it.
