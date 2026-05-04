# Config Protection Design

**Date:** 2026-04-14
**Status:** Design approved, ready for implementation plan
**Scope:** Prevent agents from bypassing tier-based restrictions on `openclaw.json`, regardless of the write path (gateway RPC, generic file tools, bash)

## Problem

Each user's OpenClaw container writes its own `openclaw.json` on EFS at `/mnt/efs/users/{user_id}/openclaw.json`. The agent inside the container has **two paths** to mutate this file, and both bypass the backend's tier enforcement at `routers/config.py:121-128`:

1. **Gateway RPC.** The LLM-callable `gateway` tool (`src/agents/tools/gateway-tool.ts:159-324`) exposes `config.patch` and `config.apply` actions. These wrap the gateway's `config.patch` RPC (`src/gateway/server-methods/config.ts:464-`), which validates against the config schema but has no per-field tier policy — it will write any schema-valid JSON the agent produces. The RPC is local to the container (loopback to the gateway); our backend does not see it.

2. **Direct file write.** The agent's general-purpose `write`/`edit` tools can write `openclaw.json` directly without going through any RPC. Even if we intercepted the gateway RPC, this path remains.

OpenClaw hot-reloads on file change either way. Both paths terminate in the same place (an on-disk JSON file) — so the enforcement point has to be at the file, not at either specific write path.

Two fields must be policy-enforced regardless of write path:

- **`models.providers`** (and dependent `agents.defaults.model.primary` / `agents.defaults.models`) — locked for everyone. Prevents agents from switching to unauthorized Bedrock models or adding entire new providers.
- **`channels.{provider}.accounts`** — locked to empty for free tier only. Prevents free-tier users from configuring Telegram/Discord/Slack bots.

Everything else in `openclaw.json` — `tools`, `hooks`, `memory`, `cron`, plugin configs, non-locked channel flags, OpenClaw's runtime `meta` block — remains freely agent-mutable. Agent-as-config-author is a deliberate product value.

## Constraints investigated and ruled out

**POSIX file permissions.** Could make `openclaw.json` root-owned + read-only to the container. Rejected: POSIX operates at whole-file granularity; the agent's legitimate edits (tools, hooks, memory, etc.) would also fail. Breaks the core product value.

**OpenClaw `tools.fs.workspaceOnly: true`.** Confines `read`/`write`/`edit` tools to the agent workspace dir, which *would* make `openclaw.json` unreachable — but it's all-or-nothing: agent also loses access to its own config. Same failure mode as POSIX.

**OpenClaw `exec-approvals` socket.** Real-time JSONL approval gate (`src/infra/exec-approvals.ts:983-1013`). Only covers shell command execution, not file writes via `write`/`edit`. Doesn't solve the primary attack path.

**Intercepting the `config.patch` gateway RPC.** The agent's `gateway` tool routes through a local loopback RPC; our backend's `GatewayConnectionPool` doesn't see that traffic. We could add a proxy inside the container or patch the gateway handler to call out for authorization, but both require OpenClaw modifications or container-side shims. Even with this layer, the direct-file-write path still bypasses it. The file is the only common choke point, so reconciliation is strictly more general.

**OpenClaw layered/overlay config.** Not supported (`src/config/paths.ts:23-24` loads a single file).

**EFS byte-range locks (`fcntl`/`flock`).** Advisory locks only; non-cooperating writer (`echo > openclaw.json`) bypasses. Not an access-control mechanism.

**Forking OpenClaw.** Ruled out as too-heavy maintenance cost for this use case. We consume `alpine/openclaw` from Docker Hub.

## Approach: backend reconciliation

The backend runs a per-user polling loop that re-reads each active user's `openclaw.json`, evaluates it against a tier-aware policy, and reverts drift on locked fields only. Reaction time ~1 second. Non-locked fields are never touched.

Defense-in-depth layers:

| Layer | Mechanism | Closes |
|-------|-----------|--------|
| 1 | Backend API policy (`routers/config.py`) | Frontend/admin PATCH path writing forbidden fields |
| 2 | Backend reconciler loop | Agent bypassing the API by writing the file directly |
| 3 | Audit logs + metrics | Observability into drift attempts |

Race window: a forbidden config is live for at most ~1 second between agent write and reconciler revert. For model changes, any usage during that window is metered by the existing usage poller and billed accordingly. For free-tier channel attempts, configuring a channel also requires a bot token + pairing flow that free-tier UI doesn't expose, so the 1-second window has no practical attack value.

## Architecture

```
  OpenClaw container (agent writes openclaw.json)
        │
        ▼
    EFS: /mnt/efs/users/{uid}/openclaw.json   (mtime updated)
        │
        ▼ (polled every ~1s)
  ConfigReconciler
        │
        ├─ mtime unchanged?  ─── yes ──▶ skip
        │                        no
        │                        ▼
        │                   fcntl.lockf EX
        │                        │
        │                        ▼
        │                 read + parse JSON
        │                        │
        │                        ▼
        │           config_policy.evaluate(config, tier)
        │                        │
        │           ┌────────────┴───────────┐
        │           │ no violations          │ violations
        │           ▼                        ▼
        │       skip write             apply_reverts(config, violations)
        │                                    │
        │                                    ▼
        │                           atomic write + chown 1000:1000
        │                                    │
        │                                    ▼
        │                          audit log + metric
        │                                    │
        ▼                                    ▼
   release lock                       release lock
```

### Components

Two new files under `apps/backend/core/services/`:

- **`config_policy.py`** — pure, side-effect-free policy module. No IO, no DB. Tier + config dict → list of violations. Reverts compute the authoritative expected value from existing helpers in `core/containers/config.py`.
- **`config_reconciler.py`** — asyncio task, runs as a FastAPI lifespan background task alongside `usage_poller.py`. Polls, locks, reconciles.

Modifications to existing files:

- **`routers/config.py`** — replace the custom `_patch_touches_channels` check with `config_policy.evaluate` on the merged result. One source of truth for policy.
- **`routers/updates.py`** — admin `PATCH /container/config/{owner_id}` and fleet patch set a DDB grace field `containers.reconciler_grace_until = now + 5s` so the reconciler doesn't immediately revert admin overrides.
- **`main.py`** — start the reconciler in the lifespan handler.
- **`core/config.py`** — add `CONFIG_RECONCILER_MODE` setting with values `off | report | enforce`.

New one-shot script:

- **`scripts/reconcile_all_configs.py`** — walks every active container and synchronously reconciles. Used during initial rollout and as a manual recovery tool.

## Policy module (`config_policy.py`)

### Public interface

```python
from typing import Any, Literal, TypedDict

LockedField = Literal[
    "models.providers",
    "agents.defaults.models",
    "agents.defaults.model.primary",
    "channels.accounts",
]

class PolicyViolation(TypedDict):
    field: LockedField
    reason: str          # human-readable, for logs + audit
    expected: Any        # revert target
    actual: Any          # what drift produced

def evaluate(config: dict, tier: str) -> list[PolicyViolation]: ...

def apply_reverts(config: dict, violations: list[PolicyViolation]) -> dict: ...
```

`evaluate()` returns an empty list if the config is legal. `apply_reverts()` deep-copies the input, overwrites only the violating fields with their expected values, and returns the result. All other keys (including OpenClaw's `meta` block) are preserved untouched.

### Expected-config computation

Reuses existing helpers to keep one source of truth for "what's allowed per tier":

- `_models_for_tier(tier)` — `core/containers/config.py:197-204`
- `_agent_models_for_tier(tier, primary)` — `core/containers/config.py:207-220`
- `_TIER_ALLOWED_MODEL_IDS` — `core/containers/config.py:178-194`
- `TIER_CONFIG` — `core/config.py`

### Violation rules

"Paid" means `starter`, `pro`, or `enterprise`. Unknown tier strings fall through to free (matches the default-deny posture in `_models_for_tier`).

| Field | Free | Paid | Revert target |
|-------|------|------|---------------|
| `models.providers` | `{"amazon-bedrock": {...free models only}}` | `{"amazon-bedrock": {...tier models}}` | Computed from `_models_for_tier(tier)` |
| `agents.defaults.models` keys | subset of tier allowlist | subset of tier allowlist | Filter out unauthorized entries, add primary |
| `agents.defaults.model.primary` | `TIER_CONFIG.free.primary_model` | any ID in tier allowlist | `TIER_CONFIG[tier].primary_model` |
| `channels.{p}.accounts` | empty `{}` or missing | no check | `{}` |

### Deliberate non-enforcements

Agent may modify these without triggering reverts:

- `channels.{p}.enabled`, `channels.{p}.dmPolicy` — scaffold flags. No accounts = no risk.
- `plugins.entries.amazon-bedrock.config.discovery` — controls plugin-side auto-discovery; doesn't expand what our IAM role can invoke.
- `plugins.entries` for non-provider plugins (perplexity, etc.)
- Top-level: `tools`, `hooks`, `memory`, `cron`, `browser`, `web`, `session`, `update`, `meta`, `skills`, `agents.defaults.workspace`, etc.

## Reconciler loop (`config_reconciler.py`)

### Structure

```python
class ConfigReconciler:
    def __init__(self, efs_mount: str, tier_cache_ttl: float = 60.0):
        self._stop = asyncio.Event()
        self._last_seen_mtime: dict[str, float] = {}
        self._tier_cache: dict[str, tuple[str, float]] = {}

    async def run_forever(self) -> None:
        while not self._stop.is_set():
            try:
                await self._tick()
            except Exception:
                logger.exception("reconciler tick failed")
            await asyncio.wait([asyncio.create_task(self._stop.wait())], timeout=1.0)
```

### Per-user check

Two-phase for efficiency:

**Phase 1 — cheap mtime gate (no parse, no lock):**

```python
try:
    mtime = await asyncio.to_thread(os.path.getmtime, config_path)
except FileNotFoundError:
    return  # container not yet provisioned
if mtime == self._last_seen_mtime.get(owner_id):
    return  # unchanged, skip
```

**Phase 2 — locked read + policy check + conditional revert:**

```python
def _mutate(current: dict) -> bool:
    violations = config_policy.evaluate(current, tier)
    if not violations:
        return False  # no write needed
    reverted = config_policy.apply_reverts(current, violations)
    current.clear()
    current.update(reverted)
    return True

await config_patcher._locked_rmw(owner_id, _mutate, "policy_revert")
```

### Reused primitives

- `config_patcher._locked_rmw` (`config_patcher.py:35-98`) — handles `fcntl.lockf` EX lock, atomic temp+rename, backup, chown to uid 1000. Zero new locking code.
- `container_repo.list_active_owners()` (new helper) — scans DDB `containers` table for `status = "running"` only. Owners in `provisioning` are excluded because the backend is actively writing `openclaw.json` during that phase (see Container provisioning race below). Owners with no container don't need reconciliation.

### Tier cache

Per-owner cache with 60s TTL. Billing changes (upgrade/downgrade) propagate within 60s + 1s poll. Cache miss → single DDB read from `billing-accounts` table.

### Admin grace window

Before reverting, reconciler checks `containers.reconciler_grace_until` in DDB. If current time < grace timestamp, skip this cycle. Set by admin patch endpoints to `now + 5s`.

### Concurrency

- At most one tick per second per user.
- Fleet parallelization via `asyncio.Semaphore(20)`.
- Admin `PATCH /config` and reconciler serialize through `_locked_rmw`'s `fcntl.lockf` EX lock.
- Agent writes compete via POSIX; any write during the reconciler's lock is flushed after unlock, picked up on the next tick.

### Failure modes

| Failure | Behavior |
|---------|----------|
| Container dir missing | Skip silently (not yet provisioned) |
| JSON parse error | Log + metric, skip this cycle (agent might be mid-write) |
| Lock contention | `fcntl.lockf` blocks, wait turn |
| DDB tier lookup fails | Log + skip (fail-open; never lock a user out of their own plan due to our DDB error) |
| EFS mount gone | Log + alert; pointless to revert on dead FS |

### Observability

- Metric `config.drift.reverted` with `tier` dimension
- Metric `config.reconciler.tick.duration`
- Metric `config.reconciler.errors` with `kind` dimension
- Audit log entry per revert in DDB `audit_logs`: `{actor: SYSTEM_ACTOR_ID, action: "config_policy_revert", owner_id, violations}`

### Shutdown

Lifespan `on_shutdown` sets `self._stop`. Reconciler finishes current tick (≤1s) and exits.

## Backend API policy (`routers/config.py`)

Replace the current custom channels check with a shared policy evaluation on the merged result. This catches subtle cases (e.g., a patch that sets `channels.telegram.enabled: true` is not a violation on its own because it only touches a scaffold flag — the merged config still has no accounts).

```python
current = await read_openclaw_config_from_efs(owner_id) or {}
merged = _deep_merge(current, body.patch)

violations = config_policy.evaluate(merged, tier)
if violations:
    raise HTTPException(
        status_code=403,
        detail={
            "code": "policy_violation",
            "fields": [v["field"] for v in violations],
            "reason": violations[0]["reason"],
        },
    )

await patch_openclaw_config(owner_id, body.patch)
```

Existing channel-specific tests in `tests/unit/routers/test_config_router.py:94-106` update to assert the new structured error shape.

### Admin endpoints

`routers/updates.py` admin `PATCH /container/config/{owner_id}` and fleet patch stay intentionally un-gated by policy — admins sometimes need emergency overrides. They DO update `containers.reconciler_grace_until = now + 5s` in DDB before patching.

## Rollout

### Phase A — report-only

Deploy reconciler with `CONFIG_RECONCILER_MODE=report`. Reads + evaluates + emits metrics + logs violations, but does NOT write. Gives ~1 day of production telemetry to confirm:

- No false positives (legitimate configs flagged as illegal)
- Actual drift rate
- Loop latency at real fleet size

### Phase B — enforce

Flip to `CONFIG_RECONCILER_MODE=enforce`. Before the flip:

- Run `scripts/reconcile_all_configs.py` as a one-shot to clean any pre-existing drift synchronously. This creates a known-clean baseline before the live loop starts enforcing.

### Tier change handling

- Upgrade free → paid: reconciler tier cache TTL (60s) means within a minute the now-permitted channel accounts stop being reverted. No user action needed.
- Downgrade paid → free: existing channel accounts get reverted (removed) within 60s + 1s. Frontend warns the user at downgrade time via existing billing-page UX.

### Container provisioning race

`ecs_manager.create_user_service` writes `openclaw.json` before the container is `status=running`. Reconciler's `list_active_owners()` filter includes `status=running` only, so provisioning writes never race with reconciler.

## Testing

### Unit — `tests/unit/services/test_config_policy.py`

Table-driven over `(tier, input_config)` → expected violations. Coverage:

- Free tier with agent-added Telegram account → violation on `channels.accounts`
- Paid tier with agent-added Telegram account → no violation
- Free tier with agent-changed primary model to Qwen → violation on `agents.defaults.model.primary`
- Any tier with agent-added `openai` provider → violation on `models.providers`
- Base config from `write_openclaw_config(tier="free")` → no violations (regression)
- Base config from `write_openclaw_config(tier="pro")` → no violations (regression)

### Unit — `tests/unit/services/test_config_reconciler.py`

Mock EFS via `tmp_path`, mock DDB tier lookups, call `_tick()` directly. Assertions:

- Unchanged mtime → no file re-read
- Changed mtime + clean config → no write
- Changed mtime + dirty config → write happens, reverted-config matches expected
- Admin grace timestamp in DDB → skip revert
- Tier cache TTL expires → fresh DDB read
- `CONFIG_RECONCILER_MODE=report` → never writes

### Integration — `tests/integration/test_config_reconciliation.py`

Wires reconciler + `config_patcher` against a real tmp EFS path with real `fcntl` locking. One happy path (dirty config reverted) and one concurrency test (admin patch and reconciler both firing at once, no corruption). Catches IO/lock bugs that unit mocks miss.

### API — extend `tests/unit/routers/test_config_router.py`

- Existing channel-specific tests updated for new structured error shape
- Paid user tries to add `openai` provider → 403 `policy_violation` with `fields: ["models.providers"]`
- Admin PATCH at `/container/config/{owner_id}` with policy-violating payload → 200, with DDB grace timestamp set

### E2E — Playwright

- Agent (via chat) adds a cron job → persists
- Agent (via chat) tries to switch primary model to unauthorized → reverts within 2s; next chat uses authorized model

## Deliverables

1. `core/services/config_policy.py` — ~150 LOC pure policy
2. `core/services/config_reconciler.py` — ~200 LOC asyncio loop
3. `routers/config.py` — swap custom channel check for `config_policy.evaluate` on merged config
4. `routers/updates.py` — set DDB grace timestamp on admin patches
5. `main.py` — lifespan-started reconciler alongside `usage_poller`
6. `core/config.py` — `CONFIG_RECONCILER_MODE` setting
7. `scripts/reconcile_all_configs.py` — one-shot fleet cleanup
8. Unit + integration + e2e tests per above
9. One new DDB field on `containers` table: `reconciler_grace_until` (number, epoch seconds)

## Out of scope for this spec

- UX around surfacing "your plan doesn't allow this" to the agent/user after a revert. Future polish: push a chat banner or system message when drift is reverted.
- Exec-approvals socket for bash-based bypass (`src/infra/exec-approvals.ts`). Valid defense-in-depth layer, but not blocking — agent doesn't use bash as its primary write path today, and reconciliation covers the residual risk. Future follow-up.
- Forking OpenClaw to add a path-level tool denylist or layered config. Heavier than justified by this problem.
