
# Resilient provisioning state machine: design spec

**Date:** 2026-04-15
**Status:** approved, ready for implementation plan

## Context

PR #265 fixed the scale-to-zero reaper by reading DDB instead of in-memory state. The reaper now queries `container_repo.get_by_status("running")` every 60s and stops idle free-tier containers. This works correctly for containers that reach `status="running"`.

However, a container provisioned on 2026-04-15 (`user_3CNDd8aX7xssuRvFFLz5ufXzsZl`) has been running in ECS for 24 hours while stuck at `status="provisioning"` in DDB. The reaper never sees it.

## Root cause

The `provisioning → running` transition relies on `_await_running_transition`, a fire-and-forget `asyncio.create_task` with a fixed 120s budget (30 attempts × 4s). The ECS task took 6+ minutes to become reachable. The poller timed out at 120s and gave up. The user left before the container became healthy. No other mechanism retries the transition.

**Timeline from production logs (`user_3CNDd8aX7xssuRvFFLz5ufXzsZl`):**

| Time (UTC) | Event |
|---|---|
| `01:40:50` | Container provisioned, `_await_running_transition` starts |
| `01:41:33` → `01:46:42` | All RPCs fail with `[Errno 111] Connect call failed` |
| `01:42:57` | `"Eager provisioning -> running transition timed out"` — poller gives up |
| `01:46:27` | Last user activity. User leaves. |
| *later* | ECS task becomes healthy. Nobody checking. |

Same bug in dev: `user_3CGfQjbn8P3n6ZzGxz1txeqEFzC` stuck at `status="provisioning"` for 3 days, running in ECS.

**Two compounding issues:**

1. **The transition is driven by an ephemeral async task.** A fixed timeout means slow starts are abandoned. A backend deploy kills the task entirely.
2. **Per-user ECS services lack the deployment circuit breaker.** If a provision genuinely fails (bad image, OOM, crash loop), ECS retries forever with no failure signal. The poller has no way to detect permanent failure vs. slow start.

## Design

### Principle

The provisioning state machine should be durable and have proper exit conditions. The poller should never give up on a timeout — it should exit only when a real state transition occurs. ECS's own deployment circuit breaker provides the definitive failure signal.

### Change 1: Enable deployment circuit breaker on per-user services

Add `deploymentConfiguration` to the `create_service` call in `ecs_manager.py`:

```python
deploymentConfiguration={
    "deploymentCircuitBreaker": {
        "enable": True,
        "rollback": False,
    }
}
```

`rollback: False` because a new service has no previous deployment to roll back to. With `desiredCount=1`, the circuit breaker trips after 2 failed task placements and sets `rolloutState="FAILED"` on the deployment.

This also applies to `start_user_service` which calls `update_service` with `forceNewDeployment=True` — the circuit breaker is a service-level setting from creation, so it applies to all subsequent deployments automatically.

**Files:** `apps/backend/core/containers/ecs_manager.py` (the `create_service` call around line 273)

### Change 2: Make `_await_running_transition` durable

Replace the fixed `for attempt in range(max_attempts)` loop with `while True`. Fixed 10s polling interval. Four exit paths:

| Condition | Action | Rationale |
|---|---|---|
| Container healthy (TCP connect to gateway port succeeds) | Write `status="running"`, `substatus="gateway_healthy"` | Success |
| DDB `status` != `"provisioning"` | Return silently | External state change (re-provision, admin stop, etc.) |
| ECS deployment `rolloutState == "FAILED"` | Write `status="error"` | Circuit breaker tripped — provision genuinely failed |
| `CancelledError` | Return | Clean backend shutdown |

The check for `rolloutState` uses `describe_services` on the user's service name and inspects `deployments[0]["rolloutState"]`. This is one additional ECS API call per poll iteration.

**Polling cost at 10s interval per stuck container:**
- 3 ECS API calls per iteration (list_tasks, describe_tasks, describe_services): free, well within rate limits
- 1 DDB read per iteration: ~$0.003/day per container
- Negligible for any realistic number of provisioning containers

**Files:** `apps/backend/core/containers/ecs_manager.py` (`_await_running_transition` method around line 885)

### Change 3: Fire the poller from `start_user_service` (cold-start restart path)

`POST /container/provision` for a stopped container calls `start_user_service` directly, which sets `status="provisioning"` but does NOT fire `_await_running_transition`. Only `provision_user_container` does. This means a cold-start restart has the same stuck-provisioning risk if the user leaves before the container becomes healthy.

**Invariant:** any code path that sets `status="provisioning"` must ensure a transition poller is running.

Add `asyncio.create_task(self._await_running_transition(user_id))` to `start_user_service`, matching what `provision_user_container` already does.

Duplicate pollers are harmless — the loser detects `status != "provisioning"` on its next DDB read and exits. No in-memory coordination needed.

**Files:** `apps/backend/core/containers/ecs_manager.py` (`start_user_service` around line 363)

### Change 4: Startup reconciler

On backend startup, scan for containers stuck in `"provisioning"` and resume the transition poller for each. `status="provisioning"` in DDB is the durable marker that the transition hasn't completed.

In the `lifespan` handler in `main.py`, after `startup_containers()`:

```python
provisioning = await container_repo.get_by_status("provisioning")
for row in provisioning:
    asyncio.create_task(
        get_ecs_manager()._await_running_transition(row["owner_id"])
    )
```

This handles:
- Backend deploy mid-transition (the most common case)
- Backend crash/restart
- Any historical stuck-provisioning rows from before this fix

**Files:** `apps/backend/main.py` (lifespan handler)

## State machine after this change

```
provision_container() ─────────────┐
    │                              │
start_user_service() (cold start)──┤
    │                              │
    ▼                              ▼
status="provisioning"    _await_running_transition (durable, no timeout)
                                │
                ┌───────────────┼───────────────┐
                │               │               │
                ▼               ▼               ▼
           ECS healthy    rolloutState     DDB status changed
                │          ="FAILED"       externally
                ▼               │               │
         status="running"       ▼               ▼
                │          status="error"   exit silently
                ▼
         run_idle_checker (every 60s, queries status="running")
                │
                ▼
         idle > 5min + free tier
                │
                ▼
         status="stopped"Ok, 
                │
                ▼ (user returns)
         POST /container/provision → start_user_service → back to top

Backend restart?
    │
    ▼
Startup reconciler: get_by_status("provisioning")
→ resume _await_running_transition for each
```

## Files touched

| File | Change |
|---|---|
| `apps/backend/core/containers/ecs_manager.py` | Enable circuit breaker in `create_service`; rewrite `_await_running_transition`; fire poller from `start_user_service` |
| `apps/backend/main.py` | Add startup reconciler in lifespan |

## Testing

### Unit tests

1. `_await_running_transition` exits with `status="running"` when `is_healthy` returns True
2. `_await_running_transition` exits with `status="error"` when `rolloutState="FAILED"`
3. `_await_running_transition` exits silently when DDB status is no longer `"provisioning"`
4. `_await_running_transition` exits on `CancelledError`
5. `start_user_service` fires `_await_running_transition` (cold-start path)
6. Startup reconciler kicks off pollers for each provisioning container

### Integration (dev)

1. Provision a new container → verify `_await_running_transition` transitions to `"running"` (even if it takes > 120s)
2. Provision with a bad image → circuit breaker trips → `status="error"` within ~30s
3. Kill backend during provisioning → restart → verify reconciler resumes and container transitions

### Prod verification (post-deploy)

1. The two currently stuck containers (`user_3CNDd8aX7xssuRvFFLz5ufXzsZl` in prod, `user_3CGfQjbn8P3n6ZzGxz1txeqEFzC` in dev) should be picked up by the startup reconciler and transition to `"running"` (if healthy) or `"error"` (if broken) on first backend restart after deploy.
2. No new stuck-provisioning containers after 24h.

## Out of scope

- Reaper changes (it correctly handles `status="running"` containers; this fix ensures containers reach that state)
- Frontend cold-start UX (splash screen during the ~30s warm-up)
- Per-user service health dashboards
c