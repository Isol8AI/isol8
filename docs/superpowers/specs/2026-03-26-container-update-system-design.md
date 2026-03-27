# Container Update System Design

**Date**: 2026-03-26
**Status**: Draft
**Issues**: #103, #39, #38, #107

## Overview

A two-track system for applying updates to user containers. Track 1 (silent) patches `openclaw.json` on EFS for zero-downtime changes like model access. Track 2 (notification) queues updates that require a container restart or replacement, letting users choose when to apply via a Tesla-style "Update Now / Tonight / Remind Later" UX.

## Key Discovery: OpenClaw File Watcher

OpenClaw has a built-in file watcher (`chokidar`) that monitors `openclaw.json` for changes. When a change is detected, it diffs the old and new config, maps changed paths to reload rules, and either hot-reloads (zero downtime) or triggers a gateway restart.

**Confirmed via testing:** Writing directly to `openclaw.json` on EFS triggers the file watcher within ~300ms. Hot-reloadable fields (models, agents, tools) apply instantly without any restart.

**Reload rules** (from `src/gateway/config-reload-plan.ts`):

| Config path | Behavior | Downtime |
|---|---|---|
| `agents.defaults.model` | Hot reload (restarts heartbeat only) | Zero |
| `agents.defaults.models` | Hot reload | Zero |
| `models.*` (providers) | Hot reload | Zero |
| `agents.*` (general) | No action (read on next use) | Zero |
| `tools.*` | No action | Zero |
| `skills.*` | No action | Zero |
| `cron.*` | Hot reload (restarts cron subsystem) | Zero |
| `hooks.*` | Hot reload (reloads hooks) | Zero |
| `gateway.*` | **Full gateway restart** | ~5-10s |
| `plugins.*` | **Full gateway restart** | ~5-10s |

**Important distinction:**
- **File watcher** (our path): Diffs changes, hot-reloads when possible, only restarts for gateway/plugin changes
- **RPC** (`config.apply` / `config.patch`): Always restarts the gateway regardless of what changed. This is for agent-initiated runtime changes, not admin updates.

We use the file watcher path exclusively — write directly to EFS, never use the RPC for admin-initiated changes.

## Track 1: Silent Apply (Zero Downtime)

### What it handles

Changes to hot-reloadable `openclaw.json` fields. No notification, no user consent needed. Applied immediately by patching the config file on EFS.

### Triggers

| Trigger | What's patched | Source |
|---|---|---|
| Tier upgrade/downgrade (model access) | `agents.defaults.model`, `agents.defaults.models`, `agents.defaults.subagents` | Stripe webhook |
| Admin pushes skill/tool changes | `tools.*`, `skills.*` | Admin API |
| Admin pushes agent config | `agents.*` | Admin API |

### Implementation

**New function: `patch_openclaw_config(owner_id, patch: dict)`**

1. Resolve EFS path: `{EFS_MOUNT_PATH}/{owner_id}/openclaw.json`
2. Acquire file lock (`fcntl.flock`) to prevent concurrent read-modify-write races
3. Read current `openclaw.json` from EFS
4. Back up to `openclaw.json.bak` (for rollback on failure)
5. Deep-merge the patch into the existing config (only update specified keys, leave everything else untouched)
6. Validate the result is valid JSON
7. Write to a temp file, then `os.rename()` for atomic replacement
8. Release file lock
9. OpenClaw file watcher detects the change and hot-applies within ~300ms
10. Verify gateway health after 2 seconds — if unhealthy, restore from backup

**Critical:** Deep-merge, not replace. If the patch only contains `agents.defaults.model`, every other field in the config stays exactly the same. This ensures `gateway.*` fields never diff and never trigger a restart.

**Concurrency:** The file lock prevents two concurrent patches (e.g., Stripe webhook + admin push) from racing. The atomic rename prevents OpenClaw from reading a half-written file.

**File:** `apps/backend/core/services/config_patcher.py`

### Integration with Stripe webhook

In `routers/billing.py`, after `update_subscription()`:

```python
# Silent patch: update model access immediately
from core.config import TIER_CONFIG
tier_config = TIER_CONFIG[new_tier]
await patch_openclaw_config(owner_id, {
    "agents": {
        "defaults": {
            "model": {"primary": tier_config["primary_model"]},
            "subagents": {"model": tier_config["subagent_model"]},
        }
    }
})
```

For model list changes, also patch `agents.defaults.models` to update the model selector aliases.

## Track 2: Notification + User Schedule (Has Downtime)

### What it handles

Changes that require a container restart or replacement:
- New OpenClaw Docker image
- Container CPU/memory changes (tier upgrade container sizing)
- Gateway config changes (`gateway.*`, `plugins.*`)

### DynamoDB: `pending-updates` table

```
PK: owner_id (String)
SK: update_id (String, ULID for time-ordering)
Attributes:
  type: "image_update" | "container_resize" | "gateway_config"
  status: "pending" | "scheduled" | "applying" | "applied" | "failed"
  scheduled_at: ISO8601 | null
  changes: {
    new_image: "ghcr.io/openclaw/openclaw:v2026.4.1" | null,
    new_cpu: "1024" | null,
    new_memory: "2048" | null,
    config_patch: {...} | null,  // for gateway.* changes only
  }
  description: "OpenClaw v2026.4.1 available"
  created_at: ISO8601
  applied_at: ISO8601 | null
  last_snoozed_at: ISO8601 | null
  force_by: ISO8601 | null  // admin can force-apply after this time
  ttl: Number  // DynamoDB TTL — auto-delete 30 days after applied_at
```

**GSI:** `status-index` with PK=`status` (String), SK=`scheduled_at` (String). Used by the scheduled worker to efficiently query `status == "scheduled"` items.

### API Endpoints

**`GET /container/updates`**
- Returns pending updates for the authenticated owner
- Accessible to all users
- Response: `[{update_id, type, description, status, created_at, scheduled_at}]`

**`POST /container/updates/{update_id}/apply`**
- Body: `{schedule: "now" | "tonight" | "remind_later"}`
- `require_org_admin(auth)` in org context
- `"now"` → apply immediately, return `{status: "applying"}`
- `"tonight"` → set `scheduled_at` to 2:00 AM UTC, return `{status: "scheduled"}`
- `"remind_later"` → no DB change, frontend stores snooze in localStorage

**`POST /container/updates`** (admin-only, internal)
- Creates pending updates for specific owner or all owners
- Body: `{owner_id: "..." | "all", type, description, changes}`
- When `owner_id: "all"`: queries all active owners from billing-accounts table, creates one pending update per owner

### Apply Logic

When a user clicks "Update Now" or the scheduled worker fires:

1. **Conditional write:** Set `status = "applying"` with a condition that `status == "pending" or "scheduled"` (prevents double-apply)
2. **If `config_patch` (gateway changes):** Read `openclaw.json` from EFS, merge patch, write back. Gateway will restart via file watcher.
3. **If `new_image` or `new_cpu/memory`:** Register new ECS task definition revision with updated values, then update ECS service with `forceNewDeployment=True`
4. **If both:** Apply config patch first, then ECS update
5. **Set `status = "applied"`, `applied_at = now`**
6. **On failure:** Set `status = "failed"`, log error. User can retry.

### Scheduled Update Worker

Background task started in `main.py` lifespan. Every 60 seconds, queries DynamoDB for updates where `status == "scheduled"` and `scheduled_at <= now()`. Applies them using the same apply logic.

### WebSocket Notification

When a pending update is created and the user is connected, push via Management API:
```json
{"type": "update_available", "update_id": "...", "description": "OpenClaw v2026.4.1 available"}
```

Frontend shows the banner immediately without waiting for poll.

## Frontend UX

### Update banner

Rendered in `AgentChatWindow.tsx`, above the chat input (same position as `BudgetExceededBanner`).

```
┌──────────────────────────────────────────────────────────┐
│ 🔄 Update available: OpenClaw v2026.4.1                  │
│                                                          │
│ Your agent needs a brief restart (~30s) to apply.        │
│                                                          │
│ [Update Now]  [Tonight at 2 AM]  [Remind Me Later]       │
└──────────────────────────────────────────────────────────┘
```

**Multiple updates:** Collapse into "2 updates available" with expandable list.

**Org members (non-admin):** "An update is available. Your admin can apply it."

**During apply:** Banner changes to spinner: "Updating your agent..."

**After apply:** Banner disappears. WebSocket disconnects briefly, `ConnectionStatusBar` shows "Reconnecting...", auto-reconnects when gateway is back.

### Snooze

- "Remind Me Later" stores `{update_id, snoozed_until: now + 24h}` in localStorage
- Banner hidden until snooze expires or next session
- Per-device, not server-side

### Polling

- `GET /container/updates` called on dashboard mount (low frequency)
- Also triggered by `update_available` WebSocket event for real-time

## Tier Upgrade Flow (Updated)

When a user upgrades from Free → Starter:

1. Stripe webhook fires `subscription.created` with `plan_tier: "starter"`
2. Backend calls `update_subscription()` → updates billing account
3. **Track 1 (silent):** `patch_openclaw_config()` → patches model access to Kimi K2.5. File watcher hot-reloads. User immediately sees new models in the selector. Zero downtime.
4. **Track 2 (if size changes):** Free and Starter are both 0.5 vCPU/1GB → no size change → no Track 2 update needed.

When upgrading Starter → Pro:

1-3. Same as above (model access patched silently)
4. **Track 2:** Pro is 1 vCPU/2GB (different from Starter's 0.5/1GB). Queue pending update: "Your container is being upgraded to Pro specs." User sees banner, picks when to apply.

When downgrading (subscription.deleted):

1. Backend reverts to free tier
2. **Track 1:** Patch model access back to MiniMax M2.1 only. Immediate.
3. **Track 2 (if size changes):** If container was Pro/Enterprise size, queue a downgrade resize. User picks when.

## Integration Points

### Issue #103: User-facing notifications
Track 2 banner with Now/Tonight/Later. Fully addressed.

### Issue #39: Fleet-wide updates
`POST /container/updates` with `owner_id: "all"` creates one pending update per active owner. Each user sees the banner and decides when. Admin can also force-apply via a separate endpoint if critical.

### Issue #38: Image detection
Upstream detection pipeline (separate concern) approves a new image → calls `POST /container/updates` with `type: "image_update"` for all owners. This spec doesn't cover the detection/validation pipeline itself, just the delivery mechanism.

### Issue #107: Billing follow-up
Container update on tier change is fully addressed via Track 1 (silent model patch) + Track 2 (container resize when needed).

## File Structure

### New files

| File | Purpose |
|---|---|
| `apps/backend/core/services/config_patcher.py` | `patch_openclaw_config(owner_id, patch)` — read/merge/write EFS |
| `apps/backend/core/repositories/update_repo.py` | DynamoDB CRUD for `pending-updates` table |
| `apps/backend/core/services/update_service.py` | Create updates, apply updates, scheduled worker |
| `apps/backend/routers/updates.py` | `GET /updates`, `POST /updates/{id}/apply`, `POST /updates` (admin) |
| `apps/backend/tests/unit/services/test_config_patcher.py` | Tests for patch logic |
| `apps/backend/tests/unit/services/test_update_service.py` | Tests for update lifecycle |
| `apps/backend/tests/unit/repositories/test_update_repo.py` | Tests for DynamoDB operations |

### Modified files

| File | Change |
|---|---|
| `apps/backend/routers/billing.py` | Stripe webhook: Track 1 silent patch + Track 2 queue for size changes |
| `apps/backend/core/containers/config.py` | Extract model config into reusable dict for patching |
| `apps/backend/main.py` | Start scheduled update worker in lifespan |
| `apps/infra/lib/stacks/database-stack.ts` | Add `pending-updates` DynamoDB table |
| `apps/infra/lib/stacks/service-stack.ts` | Wire table permissions |
| `apps/frontend/src/components/chat/AgentChatWindow.tsx` | Update banner component |
| `apps/frontend/src/hooks/useGateway.tsx` | Handle `update_available` WebSocket event |

## Owner-to-Container Mapping

Track 2 apply needs to find the ECS service for a given `owner_id`. The `container_repo` stores this mapping:

```
containers table: owner_id → {service_name, task_arn, access_point_id, status, ...}
```

The apply logic uses `container_repo.get_by_owner_id(owner_id)` to get the service name, then calls `EcsManager` methods with it. This is the same pattern used by `provision_user_container()` and the debug endpoints.

## Scheduled Worker: Single-Leader

The backend runs on EC2 behind an ASG. Multiple instances would each run the scheduled worker, causing duplicate apply attempts. The DynamoDB conditional write (`status == "pending" or "scheduled"` → `"applying"`) prevents double-apply, but multiple instances still waste resources querying and failing.

**Solution:** Use a DynamoDB-based leader lease. Before the worker loop, attempt to acquire a lease item (`PK: "worker_lease", SK: "scheduled_updates"`) with a TTL of 90 seconds. Only the instance holding the lease runs the query. The lease auto-expires if the instance dies. This is a standard pattern for single-leader election on DynamoDB.

The apply logic itself must also be idempotent — `register_task_definition` creates a new revision (safe to retry), and `update_service` with `forceNewDeployment` is idempotent.

## Mid-Session Behavior

When Track 2 "Update Now" is clicked while the user has an active chat session:

1. The banner shows a warning: "Your current conversation will be briefly interrupted (~30s). Any in-progress agent response will be lost."
2. User confirms
3. Container is replaced — WebSocket disconnects
4. `ConnectionStatusBar` shows "Reconnecting..."
5. Gateway comes back, WebSocket auto-reconnects
6. Chat history is preserved (stored on EFS in `.jsonl` files)
7. User can continue chatting — only the in-flight response (if any) is lost

For "Tonight at 2 AM" — no warning needed since the user is likely not active.

## Fleet-Wide Update Scalability

When `POST /container/updates` is called with `owner_id: "all"`:

1. The endpoint returns immediately with `{status: "queuing", job_id: "..."}`
2. A background task queries all active owners from `billing-accounts` table
3. Uses DynamoDB `batch_write_item` (25 items per batch) to create pending update records
4. Logs progress: "Queued 150/500 updates..."

This prevents HTTP timeout on large fleets and provides visibility into progress.

## Snooze Tracking

"Remind Me Later" is primarily frontend (localStorage snooze), but the backend also tracks it:

- When a user snoozes, the frontend calls `POST /container/updates/{id}/apply` with `{schedule: "remind_later"}`
- Backend sets `last_snoozed_at` on the update record (no status change)
- Admin can query: "How many users are snoozing this critical update?" via the fleet inventory

For critical security updates, admin can set `force_by: ISO8601` on the update record. If `force_by` passes and the update is still pending/snoozed, the scheduled worker auto-applies it.

## DynamoDB TTL

Applied and failed update records get a TTL of 30 days after `applied_at` or `created_at`. DynamoDB auto-deletes expired items, keeping the table lean.

The scheduled worker query uses a GSI: `status-index` with PK=`status`, SK=`scheduled_at`. This avoids full table scans. Only `"scheduled"` items are queried.

## Model Aliases Per Tier

`TIER_CONFIG` in `config.py` needs a `model_aliases` field defining which models appear in the selector per tier. The Track 1 patch includes both `agents.defaults.model` (primary) and `agents.defaults.models` (alias map).

```python
TIER_CONFIG = {
    "free": {
        ...
        "model_aliases": {
            "amazon-bedrock/us.minimax.minimax-m2-1-v1:0": {"alias": "MiniMax M2.1"},
        },
    },
    "starter": {
        ...
        "model_aliases": {
            "amazon-bedrock/us.moonshotai.kimi-k2-5-v1:0": {"alias": "Kimi K2.5"},
            "amazon-bedrock/us.minimax.minimax-m2-1-v1:0": {"alias": "MiniMax M2.1"},
        },
    },
    # ... etc
}
```

The Stripe webhook patch then includes:
```python
await patch_openclaw_config(owner_id, {
    "agents": {
        "defaults": {
            "model": {"primary": tier_config["primary_model"]},
            "models": tier_config["model_aliases"],
            "subagents": {"model": tier_config["subagent_model"]},
        }
    }
})
```

## Out of Scope

- Image detection CI pipeline (#38) — separate concern, feeds into this system
- Fleet-wide admin dashboard UI — CLI/API sufficient for now
- Update history / audit log — just track current pending updates
- Rollback mechanism — if update fails, user can retry or contact support
- Scale-to-zero for free tier — separate feature, not part of update system
