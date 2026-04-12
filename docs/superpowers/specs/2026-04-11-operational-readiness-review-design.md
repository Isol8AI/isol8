# Operational Readiness Review — Master Design

**Status:** Draft
**Date:** 2026-04-11
**Parent issue:** Isol8AI/isol8#190
**Deferred follow-up:** Isol8AI/isol8#231 (frontend product analytics — Track D)
**Branch:** `worktree-orr-specs`

---

## 1. Goal

Bring Isol8 from "zero observability" to production-grade monitoring before user rollout. This is the **canonical reference** for the metric taxonomy, severity tiers, alarm thresholds, SLOs, and runbook structure that the three implementation tracks reference. All sub-specs refer back to this document by name; nothing in the metric or alarm catalog should be re-defined elsewhere.

The shipping bar is: **on-call (currently a single human) gets a meaningful page when something breaks for users, gets a Slack/email warn when something is trending bad, and has a written runbook telling them what lever to pull for every page-level alarm.**

## 2. Background

Audited 2026-04-08 (Isol8AI/isol8#190) and re-verified 2026-04-11. Current state:

- CDK log group `/ecs/isol8-{env}` exists with 2-week retention.
- ECS task role has `cloudwatch:PutMetricData` IAM granted.
- **Zero alarms, zero dashboards, zero SNS topics, zero custom metrics, zero structured logging, zero request-id correlation.**
- Backend uses stdlib `logging` only.
- All operational issues today require manual log inspection or AWS Console drilling.

Additional gaps surfaced during the 2026-04-11 re-audit (not in #190):

1. `update_service.run_scheduled_worker()` background loop catches all exceptions and silently sleeps 60s. Stale pending-updates accumulate with no signal.
2. Clerk webhook handler has no idempotency dedup (replayed events double-process).
3. `pending-updates` DynamoDB table has TTL defined in CDK (line 108 of `database-stack.ts`), but the backend write path may not set the `ttl` attribute on every item — verify and fix if needed.
4. CLAUDE.md is stale: claims backend is on EC2 (it's Fargate), claims Terraform/Supabase/RDS (it's CDK/DynamoDB).
5. `apps/terraform/` directory may still exist with cached `.terraform/` metadata (no tracked `.tf` files) — delete if present to remove confusion.

## 3. Scope

### In scope (this ORR)

- Three implementation tracks (A, B, C — see §4 below)
- Custom metric instrumentation across the FastAPI backend
- CDK observability stack (alarms, dashboards, SNS, metric filters, canaries)
- IAM tightening on existing service stack
- AWS-account hardening (GuardDuty, Access Analyzer, Budgets, pending-updates TTL)
- Backend security fixes from #190 §3 (15 items across CRITICAL/HIGH/MEDIUM — item 10 is IAM, lives in Track B)
- CLAUDE.md cleanup + `apps/terraform/` deletion
- Runbook stubs for every page-level alarm

### Out of scope (deferred)

- **Frontend product analytics** (PostHog, Sentry, Vercel Speed Insights, conversion funnel events) — see Isol8AI/isol8#231. Spun out to keep this ORR focused on backend health vs. user-behavior tracking.
- **Growth agent integration** (LLM querying PostHog HogQL) — depends on #231.
- **GooseTown observability** — the 2026-04-11 audit confirmed there is no active GooseTown router in the current backend. If the simulation is reactivated, observability for it gets its own follow-up.
- **Tauri desktop app telemetry** — separate project.
- **Slack webhook subscription on the warn topic** — TODO marker; will add when the Slack workspace + incoming webhook URL are set up. Until then, warn tier is email-only.
- **PagerDuty integration on the page topic** — TODO marker; will add when account exists. Until then, page tier is SMS-to-phone + email.

## 4. Architecture

### 4.1 Document hierarchy

Four spec documents, all under `docs/superpowers/specs/`:

1. **`2026-04-11-operational-readiness-review-design.md`** ← this file (master)
2. **`2026-04-11-orr-track-a-backend-observability-design.md`** (Track A)
3. **`2026-04-11-orr-track-b-cdk-observability-design.md`** (Track B)
4. **`2026-04-11-orr-track-c-backend-security-design.md`** (Track C)

The sub-specs reference this master for the metric taxonomy and alarm catalog. **Do not redefine metric names, dimensions, or alarm thresholds in the sub-specs** — pointing back to this document is the coordination mechanism.

### 4.2 Track decomposition

| Track | Scope | Owns |
|---|---|---|
| **A** | Backend observability foundation + instrumentation + runbook stubs | `apps/backend/core/observability/*` (new), `apps/backend/main.py` (middleware), wrapping ~49 emit sites in services and routers, `docs/ops/runbooks/*` (new) |
| **B** | CDK observability stack + IAM tightening + AWS-account hardening | `apps/infra/lib/stacks/observability-stack.ts` (new), `apps/infra/lib/stacks/service-stack.ts` (IAM tightening = #190 §3 item 10), `apps/infra/lib/app.ts` (wire new stack), `apps/terraform/` (delete if present). Note: 7 existing stacks (auth, dns, network, database, container, service, api). |
| **C** | Backend security fixes + docs cleanup | `apps/backend/routers/{updates,debug,proxy,billing,control_ui_proxy,webhooks}.py`, `apps/backend/core/auth.py`, `apps/backend/core/containers/workspace.py`, `apps/backend/core/services/key_service.py`, `CLAUDE.md`, `apps/backend/core/services/dynamodb_helper.py` (new — wraps boto3 with metric emit) |

### 4.3 Coordination model

The master spec **freezes the metric taxonomy** (every metric name, every dimension, every unit) before any code is written. Track A emits against the exact names listed in §6. Track B authors CloudWatch alarms against the exact same names. Because both tracks reference the same frozen list, they can be developed in parallel and the merge is conflict-free by construction.

Cross-track touch points:
- **Track A and Track C** both edit some router files (`updates.py`, `debug.py`, `proxy.py`, `billing.py`, `auth.py`, `workspace.py`). Track A's edits are additive (adds `metrics.put_metric()` and structured log calls); Track C's edits are logic changes (idempotency, rate limits, bounds checks). Conflicts at merge time are expected to be trivial — both tracks should import the metrics helper from Track A's `core/observability/metrics` module by the same name.
- **Track C item: DynamoDB throttle wrapper.** This is a new helper (`core/services/dynamodb_helper.py`) that wraps boto3 calls and emits `dynamodb.throttle` and `dynamodb.error` metrics. Track A defines the metrics; Track C builds the wrapper because it's tied to the security/reliability story. Existing call sites get migrated incrementally.
- **Track B item: pending-updates TTL.** Adding a TTL attribute to the existing DynamoDB table requires a CDK change, which is Track B's territory. Track C does NOT touch the table definition.

### 4.4 Execution model

- I (the lead) create a team via `TeamCreate(team_name="isol8-orr")`.
- Three teammates spawn, each in its own git worktree:
  - `track-a-backend-obs` — runs the Track A plan
  - `track-b-cdk-infra` — runs the Track B plan
  - `track-c-security` — runs the Track C plan
- Each teammate has its own context window, manages its own internal todo list, and reports back via SendMessage when done or blocked.
- Shared task list (the team's TaskList) holds three top-level tasks (one per teammate). Teammates update status as they progress.
- Cross-teammate communication via SendMessage if a teammate discovers a taxonomy gap mid-flight (e.g., "I need a metric for X that isn't in the master spec"). Lead resolves by editing the master spec and broadcasting the change.

### 4.5 Approval gates

The user (the human running the lead session) approves at:

1. **After all 4 specs are written** — this checkpoint, before plans are written
2. **After all 3 plans are written** — before teammates are spawned
3. **After each teammate's branch returns** — before any PR is opened
4. **Before any `git push`** — always, per the persistent feedback memory

The lead never pushes without explicit user approval.

## 5. Severity tiers

### 5.1 Page tier

- **SNS topic:** `isol8-{env}-alerts-page`
- **Subscriptions:**
  - SMS to on-call phone (number stored in Secrets Manager as `isol8/{env}/oncall/phone`)
  - Email to `oncall@<your-domain>` (audit trail; survives if SMS provider drops)
- **When:** customer impact in progress, security event, data loss risk
- **Steady-state target:** **never fires** — every page is an incident
- **Cost note:** ~$0.01/SMS in US; negligible at expected volume
- **TODO:** upgrade to PagerDuty when account exists

### 5.2 Warn tier

- **SNS topic:** `isol8-{env}-alerts-warn`
- **Subscriptions:**
  - Email to `alerts@<your-domain>`
  - **TODO:** Slack webhook when workspace + incoming webhook URL are set up
- **When:** trending bad, capacity creep, cost anomaly, single failure that doesn't yet hurt customers
- **Steady-state target:** very few — should be reviewable in <5 min business hours

### 5.3 Routing logic

Every alarm in §7 is annotated with one of `Page` or `Warn`. CDK creates one `cloudwatch.Alarm` per row, sets its `alarmAction` to the matching SNS topic via `cloudwatch_actions.SnsAction`.

## 6. Metric taxonomy

### 6.1 Conventions

- **Name format:** `<domain>.<event>[.<sub_event>]`
- **Casing:** lowercase, dot-separated, snake_case within segments
- **Standard dimensions on every metric:**
  - `env` ∈ {`dev`, `prod`} — set from `ENVIRONMENT` env var at startup
  - `service` — emitting service identifier (`isol8-backend` for the FastAPI app)
- **Unit conventions:**
  - Counters: `Count`, with dimension `status` ∈ {`ok`, `error`} for success/fail rates
  - Timings: `Milliseconds`, name suffix `.latency`
  - Gauges: `Count`, emitted periodically as a level (e.g., `gateway.connection.open`)
- **Cardinality discipline:** dimensions must have bounded value sets (≤ ~50 distinct values). `user_id`, `container_id`, `request_id` are **NOT** metric dimensions — they go in structured log fields only.
- **Rate computation:** rates derived in CloudWatch via metric math (`100 * error/total`), not pre-computed in the backend.

### 6.2 Emission mechanism: EMF

Backend emits metrics via **Embedded Metric Format (EMF)** — JSON log lines with an `_aws.CloudWatchMetrics` envelope. CloudWatch automatically extracts metrics from the log stream. Benefits over `PutMetricData`:

- No extra network calls (uses existing log stream)
- No new IAM permissions needed
- Supports high-cardinality dimensions in the log fields without making them metric dimensions
- Cheaper at scale

EMF spec: <https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch_Embedded_Metric_Format.html>

The Track A spec defines the helper API (`core/observability/metrics.py`) that emits EMF-formatted log lines.

### 6.3 Full metric catalog

49 metrics across 12 domains. The catalog below is **frozen** — Track A emits exactly these names; Track B authors alarms against exactly these names. New metrics during implementation require updating this section and broadcasting via SendMessage.

#### Container lifecycle (`apps/backend/core/containers/ecs_manager.py`)

| Metric | Unit | Dimensions | Description |
|---|---|---|---|
| `container.provision` | Count | `status` | Provision attempt outcome (CreateService, register task def, set up access point) |
| `container.lifecycle.state_change` | Count | `state` | One per state transition: starting, running, stopping, stopped |
| `container.lifecycle.latency` | Milliseconds | `op` | Time for start or stop op to complete |
| `container.efs.access_point` | Count | `op`, `status` | EFS access point create/delete |
| `container.task_def.register` | Count | `status` | Task definition registration |
| `container.error_state` | Count | — | Stuck or error state detected (page on any) |

#### Gateway connection pool (`apps/backend/core/gateway/connection_pool.py`)

| Metric | Unit | Dimensions | Description |
|---|---|---|---|
| `gateway.connection` | Count | `event` | event ∈ {connect, disconnect, error} |
| `gateway.connection.open` | Count (gauge) | — | Currently open backend↔container connections, emitted every 30s |
| `gateway.health_check.timeout` | Count | — | Health-check ping to a container timed out |
| `gateway.frontend.prune` | Count | — | Frontend connection pruned (idle/dead) |
| `gateway.idle.scale_to_zero` | Count | — | Free-tier container stopped due to idle |
| `gateway.reconnect` | Count | — | Reconnect attempt (alarm via anomaly detection) |
| `gateway.rpc.error` | Count | `method` | RPC error per method name (~20 methods, bounded) |

#### Chat pipeline (`apps/backend/routers/websocket_chat.py`, `core/gateway/connection_pool.py`)

| Metric | Unit | Dimensions | Description |
|---|---|---|---|
| `chat.message.count` | Count | — | Successful chat finals |
| `chat.e2e.latency` | Milliseconds | — | End-to-end: user message in → final out |
| `chat.error` | Count | `reason` | reason ∈ {timeout, bedrock_error, container_unreachable, agent_error, aborted} |
| `chat.session_usage.fetch.error` | Count | — | Failed to pull session usage from container |
| `chat.bedrock.throttle` | Count | — | Bedrock throttle propagated from container |

#### Channels (`apps/backend/routers/channels.py`)

| Metric | Unit | Dimensions | Description |
|---|---|---|---|
| `channel.rpc` | Count | `provider`, `status` | provider ∈ {telegram, discord, whatsapp} |
| `channel.configure` | Count | `provider`, `status` | Channel configure step outcome |
| `channel.webhook.inbound` | Count | `provider` | Incoming webhook from a channel provider |

#### Stripe (`apps/backend/routers/billing.py`, `core/services/billing_service.py`, `core/services/usage_service.py`)

| Metric | Unit | Dimensions | Description |
|---|---|---|---|
| `stripe.webhook.received` | Count | `event_type` | Stripe webhook ingested (~15 event types we care about) |
| `stripe.webhook.sig_fail` | Count | — | Signature verification failed (page on any) |
| `stripe.webhook.duplicate` | Count | — | Idempotency dedup hit (event already processed) |
| `stripe.meter_event.fail` | Count | — | Meter event report to Stripe failed |
| `stripe.subscription` | Count | `event` | event ∈ {created, updated, deleted, payment_failed} |
| `stripe.subscription.latency` | Milliseconds | `event` | Time to process a subscription webhook end-to-end |
| `stripe.api.latency` | Milliseconds | `op` | Outbound Stripe API call latency (op = method name) |
| `stripe.api.error` | Count | `op`, `error_code` | Outbound Stripe API call errors |

#### Clerk webhook (`apps/backend/routers/webhooks.py`)

| Metric | Unit | Dimensions | Description |
|---|---|---|---|
| `webhook.clerk.received` | Count | `event_type` | Clerk webhook ingested |
| `webhook.clerk.sig_fail` | Count | — | Svix signature verification failed |
| `webhook.clerk.duplicate` | Count | — | Idempotency dedup hit |

#### Billing internals (`apps/backend/core/services/usage_service.py`)

| Metric | Unit | Dimensions | Description |
|---|---|---|---|
| `billing.budget_check.error` | Count | — | Budget check failed (couldn't determine if user is over) |
| `billing.pricing.missing_model` | Count | — | A chat used a model that has no pricing row (page on any) |

#### Auth (`apps/backend/core/auth.py`)

| Metric | Unit | Dimensions | Description |
|---|---|---|---|
| `auth.jwt.fail` | Count | `reason` | reason ∈ {expired, signature, format, jwks_unavailable, missing_claim} |
| `auth.jwks.refresh` | Count | `status` | JWKS cache refresh outcome |
| `auth.org_admin.denied` | Count | — | Org admin check denied a request |

#### DynamoDB wrapper (`apps/backend/core/services/dynamodb_helper.py` — new in Track C)

| Metric | Unit | Dimensions | Description |
|---|---|---|---|
| `dynamodb.throttle` | Count | `table`, `op` | op ∈ {get, put, update, delete, query, scan} |
| `dynamodb.error` | Count | `table`, `op`, `error_code` | Non-throttle errors |

#### Workspace (`apps/backend/core/containers/workspace.py`)

| Metric | Unit | Dimensions | Description |
|---|---|---|---|
| `workspace.file.write.error` | Count | — | EFS file write failure |
| `workspace.path_traversal.attempt` | Count | — | Path traversal blocked (page on any — security event) |

#### Proxy (`apps/backend/routers/proxy.py`)

| Metric | Unit | Dimensions | Description |
|---|---|---|---|
| `proxy.upstream` | Count | `host`, `status` | host ∈ {perplexity, …}; bounded |
| `proxy.upstream.latency` | Milliseconds | `host` | Outbound proxy call latency |
| `proxy.auth.fail` | Count | — | Caller authn failed |
| `proxy.budget_check.fail` | Count | — | Free-tier user exceeded proxy budget |

#### Update worker (`apps/backend/core/services/update_service.py`, `routers/updates.py`)

| Metric | Unit | Dimensions | Description |
|---|---|---|---|
| `update.scheduled_worker.heartbeat` | Count | — | Emitted every loop iteration of `run_scheduled_worker` (alarm if absent) |
| `update.scheduled_worker.error` | Count | — | Loop iteration caught an exception |
| `update.fleet_patch.invoked` | Count | — | `PATCH /container/config` (no owner_id) called — page on any |
| `update.config_patch.applied` | Count | `scope` | scope ∈ {single, fleet} |

#### Debug (`apps/backend/routers/debug.py`)

| Metric | Unit | Dimensions | Description |
|---|---|---|---|
| `debug.endpoint.prod_hit` | Count | `endpoint` | A debug endpoint was hit in prod (page on any — should be 403'd) |

**Total: 49 custom metrics across 12 domains.**

## 7. Alarm catalog

### 7.1 Page tier (11 alarms)

| ID | Alarm | Trigger | Source |
|---|---|---|---|
| P1 | container-error-state | `container.error_state > 0` for 1 period of 1 min | Custom metric |
| P2 | stripe-webhook-sig-fail | `stripe.webhook.sig_fail > 0` for 1 period of 1 min | Custom metric |
| P3 | workspace-path-traversal | `workspace.path_traversal.attempt > 0` for 1 period of 1 min | Custom metric |
| P4 | update-fleet-patch-invoked | `update.fleet_patch.invoked > 0` for 1 period of 1 min | Custom metric |
| P5 | debug-endpoint-prod-hit | `debug.endpoint.prod_hit > 0` for 1 period of 1 min | Custom metric |
| P6 | billing-pricing-missing-model | `billing.pricing.missing_model > 0` for 1 period of 1 min | Custom metric |
| P7 | update-worker-stalled | `update.scheduled_worker.heartbeat` SUM == 0 for 5 min | Custom metric (heartbeat absence) |
| P8 | dynamodb-throttle-sustained | `dynamodb.throttle > 0` for 2 consecutive 1-min periods, any table | Custom metric |
| P9 | alb-5xx-rate | ALB `HTTPCode_Target_5XX_Count / RequestCount > 0.05` for 5 min | AWS-native (metric math) |
| P10 | apigw-ws-5xx-rate | API GW WebSocket `5XXError / Count > 0.05` for 5 min | AWS-native (metric math) |
| P11 | chat-canary-fail | Chat round-trip canary fails 2-of-3 consecutive runs | CloudWatch Synthetics |

### 7.2 Warn tier — backend custom metrics (27 alarms)

#### Container & gateway (8)

| ID | Alarm | Trigger |
|---|---|---|
| W1 | container-provision-error-rate | `container.provision{status=error} / SUM > 0.05` over 10 min |
| W2 | container-lifecycle-latency-p99 | `container.lifecycle.latency` p99 > 60s over 10 min |
| W3 | container-efs-access-point-fail | `container.efs.access_point{status=error} > 0` |
| W4 | container-task-def-register-fail | `container.task_def.register{status=error} > 0` |
| W5 | gateway-connection-drop | `gateway.connection.open` drops > 20% in 5 min (anomaly detection) |
| W6 | gateway-health-check-timeout | `gateway.health_check.timeout > 5` in 5 min |
| W7 | gateway-frontend-prune-storm | `gateway.frontend.prune > 100` in 1 hour |
| W8 | gateway-rpc-error-rate | `gateway.rpc.error / SUM > 0.01` over 5 min |

#### Chat (4)

| ID | Alarm | Trigger |
|---|---|---|
| W9 | chat-e2e-latency-p99 | `chat.e2e.latency` p99 > 20s over 5 min |
| W10 | chat-error-rate | `chat.error / chat.message.count > 0.01` over 5 min |
| W11 | chat-session-usage-fetch-error | `chat.session_usage.fetch.error > 0` |
| W12 | chat-bedrock-throttle | `chat.bedrock.throttle > 5` in 1 min |

#### Channels (3)

| ID | Alarm | Trigger |
|---|---|---|
| W13 | channel-rpc-error-rate | `channel.rpc{status=error} > 10` per provider per hour |
| W14 | channel-configure-fail | `channel.configure{status=error} > 0` |
| W15 | channel-webhook-inbound-absent | `channel.webhook.inbound` SUM per provider == 0 for 15 min |

#### Stripe & billing (5)

| ID | Alarm | Trigger |
|---|---|---|
| W16 | stripe-meter-event-fail | `stripe.meter_event.fail > 5` per day |
| W17 | stripe-subscription-latency | `stripe.subscription.latency` p99 > 2s |
| W18 | stripe-api-error-rate | `stripe.api.error / SUM > 0.01` over 5 min |
| W19 | billing-budget-check-error | `billing.budget_check.error > 10` per day |
| W20 | webhook-clerk-sig-fail | `webhook.clerk.sig_fail > 0` |

#### Auth (3)

| ID | Alarm | Trigger |
|---|---|---|
| W21 | auth-jwt-fail-spike | `auth.jwt.fail > 100` per hour (possible attack) |
| W22 | auth-jwks-refresh-fail | `auth.jwks.refresh{status=error} > 0` |
| W23 | auth-org-admin-denied-spike | `auth.org_admin.denied > 50` per hour |

#### Workspace, proxy, update (4)

| ID | Alarm | Trigger |
|---|---|---|
| W24 | workspace-file-write-error | `workspace.file.write.error > 10` per hour |
| W25 | proxy-upstream-5xx | `proxy.upstream{status=5xx} > 5` per host per minute |
| W26 | proxy-budget-check-fail | `proxy.budget_check.fail > 0` |
| W27 | update-worker-error | `update.scheduled_worker.error > 0` |

### 7.3 Warn tier — AWS-native infrastructure alarms (21)

These come "free" — no instrumentation required, just CDK alarm definitions over AWS-published metrics.

#### Load balancer (2)
| ID | Metric | Trigger |
|---|---|---|
| W28 | ALB `UnHealthyHostCount` | > 0 sustained 5 min |
| W29 | ALB `TargetResponseTime` p99 | > 5s |

#### API Gateway WebSocket (3)
| ID | Metric | Trigger |
|---|---|---|
| W30 | API GW WS `4XXError` rate | > 5% |
| W31 | API GW WS `IntegrationLatency` p99 | > 2s |
| W32 | API GW WS `ConnectCount` | drop anomaly |

#### Lambda authorizer (3)
| ID | Metric | Trigger |
|---|---|---|
| W33 | Lambda `Errors` | > 0 |
| W34 | Lambda `Throttles` | > 0 |
| W35 | Lambda `Duration` p99 | > 1s |

#### ECS (4)
| ID | Metric | Trigger |
|---|---|---|
| W36 | Backend service `RunningTaskCount != DesiredTaskCount` | sustained 5 min |
| W37 | ECS cluster `CPUUtilization` | > 80% |
| W38 | ECS cluster `MemoryUtilization` | > 80% |
| W39 | Fargate `TaskStopped` non-essential reason (via EventBridge → metric filter) | > 0 |

#### DynamoDB (3)
| ID | Metric | Trigger |
|---|---|---|
| W40 | `ConsumedReadCapacityUnits` per table | > 80% of provisioned (or anomaly on on-demand) |
| W41 | `ConsumedWriteCapacityUnits` per table | > 80% |
| W42 | `SystemErrors` per table | > 0 |

#### EFS (3)
| ID | Metric | Trigger |
|---|---|---|
| W43 | EFS `PercentIOLimit` | > 80% |
| W44 | EFS `BurstCreditBalance` | low |
| W45 | EFS `ClientConnections` | drop anomaly |

#### Bedrock (2)
| ID | Metric | Trigger |
|---|---|---|
| W46 | Bedrock `ModelInvocationThrottles` | > 0 |
| W47 | Bedrock `InvocationClientErrors` | > 5 / min |

#### Network (1)
| ID | Metric | Trigger |
|---|---|---|
| W48 | NLB / Cloud Map healthy host count | drop |

### 7.4 Warn tier — cost (3)

| ID | Alarm | Trigger |
|---|---|---|
| W49a | aws-budget-monthly-warn | AWS Budget at 80% threshold (warn tier) |
| W49b | aws-budget-monthly-page | AWS Budget at 100% threshold (**overrides to page tier** — uses `pageTopic`) |
| W50 | bedrock-spend-anomaly | CloudWatch Anomaly Detection on Bedrock cost metric |
| W51 | nat-gateway-data-transfer | NAT GW data transfer cost anomaly |

### 7.5 Warn tier — synthetic canaries (2)

| ID | Canary | Trigger |
|---|---|---|
| W52 | health-canary | `/health` canary fails 2-of-3 consecutive |
| W53 | stripe-webhook-replay-canary | Daily replay of a known-good Stripe webhook fails (verifies signature handler is healthy) |

**Totals:** 11 page-tier alarms + 54 warn-tier alarms = **65 alarms** (W49 split into 2 CDK constructs).

CloudWatch alarm cost: ~$0.10/alarm/month × 65 = **~$6.50/month**.

## 8. SLOs

Published on the dashboard, computed via metric math from §6 metrics.

| SLO | Target | Source |
|---|---|---|
| Chat success rate | 99.5% / 30 days | `1 - SUM(chat.error) / SUM(chat.message.count)` |
| Chat p99 latency | < 20s | `chat.e2e.latency` p99 |
| Container provision success | 99% / 30 days | `SUM(container.provision{status=ok}) / SUM(container.provision)` |
| Gateway availability | 99.9% | Synthetic canary uptime + `gateway.connection.open` gauge |
| Stripe webhook success | 100% | `stripe.webhook.sig_fail == 0` AND alarm history |
| DynamoDB throttle budget | 0 | `SUM(dynamodb.throttle) == 0` |

## 9. Synthetic canaries

Three CloudWatch Synthetics canaries, all defined in CDK in Track B.

### 9.1 `/health` canary

- **Schedule:** every 1 minute
- **Action:** HTTP GET on `https://api-{env}.isol8.co/health`, assert 200 + JSON body
- **Alarm:** W52 (warn) — fails 2 of 3 consecutive runs
- **Cost:** ~$0/mo at 1-min cadence (within free tier)

### 9.2 Chat round-trip canary

- **Schedule:** every 15 minutes
- **Action:**
  1. Read canary credentials from Secrets Manager (`isol8/{env}/canary/credentials` — Clerk email + password)
  2. Sign in to Clerk via the dev sign-in API, get a session JWT
  3. Open WebSocket to `wss://ws-{env}.isol8.co/`
  4. Send `agent_chat` message: "ping"
  5. Assert `chat.final` event arrives within 20s
  6. Sign out cleanly
- **Alarm:** P11 (page) — fails 2 of 3 consecutive runs (so a real outage pages within ~30-45 min)
- **Cost:** ~$6-60/month (96 runs/day × Bedrock free-tier model + Synthetics fees)
- **Account:** new dedicated `isol8-canary@<your-domain>` Clerk account, manually created via Clerk dashboard, never used for anything else
- **Idempotency:** must be safe to run thousands of times — does not create/delete agents, does not touch billing, only sends a chat message

### 9.3 Stripe webhook replay canary

- **Schedule:** daily at 03:00 UTC
- **Action:** POST a known-good test Stripe webhook payload (signed with test mode secret) to `/api/v1/billing/webhooks/stripe`, assert 200 + idempotency dedup
- **Alarm:** W53 (warn) — single failure
- **Purpose:** verifies the signature handler hasn't broken silently after a deploy
- **Cost:** negligible

## 10. Runbook structure

Every page-level alarm gets a runbook at `docs/ops/runbooks/{alarm_id}.md`. Track A creates one stub per page alarm; the on-call human fills in the "Known false positives" section as they're observed.

Template:

```markdown
# Alarm {ID}: {alarm_name}

**Severity:** Page
**SNS topic:** isol8-{env}-alerts-page

## What it means
{1 sentence on what triggered}

## Customer impact
{What users experience right now}

## Immediate actions
1. {step}
2. {step}
3. {if applicable: how to mitigate without root-causing}

## Investigation
- Dashboard: {link to CloudWatch dashboard widget}
- Logs query (CloudWatch Insights):
  ```
  fields @timestamp, request_id, user_id, message
  | filter ...
  | sort @timestamp desc
  ```
- Recent deploys: `gh run list --repo Isol8AI/isol8 --workflow=deploy --limit=10`

## Escalation
- Primary: on-call (you)
- Secondary: TBD when team grows

## Known false positives
{List as observed}
```

## 11. Test strategy

### Track A
- Unit tests for metric emitter (EMF JSON serialization, dimension validation, cardinality limits)
- Unit tests for logging context propagation across async boundaries (asyncio contextvars)
- Integration test: hit a router endpoint, assert `request_id` appears in resulting log line and response header
- Smoke test: deploy to dev, verify all 49 metric names appear in CloudWatch metrics namespace within 1 hour of normal traffic

### Track B
- CDK snapshot tests for the new observability stack
- `cdk synth` + `cdk diff` against current dev account — review every change
- Deploy to dev, manually publish to each SNS topic, verify SMS + email arrival
- Verify dashboard renders with the current dev metric set (some widgets may be empty until traffic generates them)
- Manually trigger each canary, verify expected outcome
- IAM tightening: deploy + run the existing E2E test suite (currently disabled) to catch any new permission denials

### Track C
- Unit tests per security fix
- Idempotency: replay a Stripe webhook 5×, assert single processing (1 row in dedup table, no duplicate billing mutations)
- Path traversal: attempt 10 known escape patterns, assert all blocked + `workspace.path_traversal.attempt` counter increments
- Cross-tenant fleet patch: org admin from org A calls `PATCH /container/config/{owner_id_in_org_b}`, assert 403
- Debug endpoint allow-list: hit each debug endpoint with `ENVIRONMENT=prod`, assert 403 + `debug.endpoint.prod_hit` increment
- JWKS stale fallback cap: simulate JWKS fetch failure, assert cache serves stale up to 15 min then fails closed

## 12. Rollout strategy

1. **All three branches developed in parallel** in worktrees, each on its own branch (`worktree-track-a-backend-obs`, `-b-cdk-infra`, `-c-security`).
2. **Track A merges first.** Metrics start flowing into CloudWatch. No alarms exist yet → no false pages. Verify metric names match this spec by inspecting the CloudWatch metrics namespace.
3. **Track B merges second.** Alarms come online. Some may immediately fire (e.g., a stale ECS task that was already in a weird state). Investigate each, decide if it's a real issue or a false positive, adjust threshold if needed.
4. **Track C merges third.** Backend security fixes go live. Each fix's alarm should already exist (added by Track B against the metric names from this spec).
5. **Each track gets PR review independently** before merge. The user reviews; the lead never merges without approval.

If a teammate finishes early, they idle and wait. If a teammate gets stuck, they SendMessage the lead. Lead may reassign work or escalate to user.

## 13. Definition of done (master)

The ORR is "done" when:

- [ ] All 4 spec docs committed and reviewed
- [ ] All 3 implementation plans committed and reviewed
- [ ] Track A branch merged: 49 custom metrics visible in CloudWatch
- [ ] Track B branch merged: 64 alarms visible in CloudWatch console, all in OK state (not insufficient data) within 1 hour of metric flow
- [ ] Track C branch merged: 15 security fixes verified by tests (item 10 is in Track B)
- [ ] All 11 page-level runbooks have stubs (full content can be filled in over time)
- [ ] CLAUDE.md updated and `apps/terraform/` deleted
- [ ] Synthetic canaries running, both green
- [ ] Page-tier SMS verified (manual: publish a test message, confirm phone receives it)
- [ ] Dashboard URL bookmarked and shared
- [ ] Track D issue (#231) referenced from #190

## 14. References

- Isol8AI/isol8#190 — Original ORR audit issue (parent)
- Isol8AI/isol8#231 — Track D follow-up (frontend product analytics, deferred)
- `CLAUDE.md` — Project conventions and current architecture
- AWS EMF spec: <https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch_Embedded_Metric_Format.html>
- CloudWatch Synthetics: <https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch_Synthetics_Canaries.html>
