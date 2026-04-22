# admin.isol8.co — Internal Admin Dashboard

**Date:** 2026-04-21
**Status:** Draft — planning-complete, implementation pending
**Tracking issue:** [Isol8AI/isol8#351](https://github.com/Isol8AI/isol8/issues/351)
**Plan:** [`docs/superpowers/plans/2026-04-21-admin-dashboard.md`](../plans/2026-04-21-admin-dashboard.md)
**Review:** gstack `/plan-ceo-review` run 2026-04-21, mode = **HOLD SCOPE** — 18 defects folded into v1, 8 scope-addition candidates deferred to Phase 2.

## Summary

A dedicated admin surface at `admin.isol8.co` lets the Isol8 team debug user issues without jumping between Clerk, Stripe, AWS Console, CloudWatch, and PostHog. Each user's full state — identity, billing, container, agents, frontend activity, backend logs — is surfaced on one page. A bounded set of safe admin actions (container reprovision, billing adjustments, account controls, config overrides, per-agent actions) is available inline, with every action audited forever in a dedicated DynamoDB table. A `/admin/health` page surfaces platform-wide system status.

The admin surface lives as a **route group inside `apps/frontend/`** (not a separate Next.js app), gated by host-based middleware so `/admin/*` is only reachable from the `admin.isol8.co` hostname. Cloudflare Access fronts the subdomain as an SSO edge gate. Backend enforcement is `Depends(require_platform_admin)` — the Clerk-user-ID allowlist from `PLATFORM_ADMIN_USER_IDS` env var.

## Goals

- Admins can find any user by email or Clerk ID and see everything about them on one page — identity, billing, container, agents, frontend activity, backend logs — in under 60 seconds.
- Common support actions (reprovision a stuck container, cancel a subscription, issue a credit, delete a misbehaving agent) are one click + typed-confirmation away.
- Every admin write action is audited forever: actor, target, action, payload, result, HTTP status, elapsed time, user-agent, IP.
- The admin surface is invisible from the public internet (Cloudflare Access edge gate) and gated server-side by the platform-admin allowlist (belt and braces).
- Zero risk of admin code leaking into the public user-facing bundle: Server Components by default, Server Actions for writes, ESLint import-boundary enforcement.
- `/admin/health` answers "is the platform OK right now?" in one view — fleet counts, upstream probes, background-task status, recent errors, recent admin activity.
- CloudWatch errors for a specific user render inline on the Logs tab — no AWS Console hop for the common case.

## Non-goals (v1)

- **Impersonation / "view as user"** — admins observe; they don't assume identity. Phase 2.
- **Correlated activity timeline** — per-source panels in v1; merging admin-actions + PostHog + sessions + container events into one time-ordered stream is Phase 2.
- **Full CloudWatch search UI** — v1 ships inline recent errors + a deep link to AWS Console for cross-user / longer-range search. A custom search UI is Phase 2.
- **Fleet-wide dashboards** — `/admin/health` gives basic fleet counts; richer fleet view is Phase 2.
- **Self-service admin add/remove** — admins are added/removed via a Secrets Manager edit + deploy. Self-service UI is Phase 2.
- **Rate-limit on admin writes** — a blast-radius guardrail, deferred to Phase 2 alongside 2FA enforcement.
- **Correlation IDs threaded through admin actions + downstream calls** — deferred to Phase 2.
- **Slack alerts on destructive admin actions** — deferred to Phase 2.
- **Two-person rule on high-risk actions** — deferred to Phase 2.

## Architecture

```
 admin.isol8.co (end-user browser)
        │
        ▼
 ┌──────────────────────────┐
 │  Cloudflare Access       │  SSO via GitHub / Google; only
 │  (edge gate, prod/dev)   │  allowlisted email domains reach Vercel.
 └────────┬─────────────────┘
          │
          ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │  Vercel (single project: isol8-frontend-*)                       │
 │                                                                  │
 │   apps/frontend/ — Next.js 16 App Router, React 19               │
 │     src/middleware.ts                                            │
 │       ├─ host === 'admin.isol8.co'       → /admin/*              │
 │       ├─ host === 'admin-dev.isol8.co'   → /admin/*              │
 │       ├─ host === any other              → 404 /admin/*          │
 │       └─ Clerk auth on /admin/*                                  │
 │                                                                  │
 │     src/app/admin/*                                              │
 │       Server Components by default (no admin client JS)          │
 │       Server Actions for writes (no fetch client code)           │
 │                                                                  │
 │     src/components/admin/*                                       │
 │       ESLint import-boundary rule blocks non-admin imports       │
 └────────┬─────────────────────────────────────────────────────────┘
          │  fetch('/api/v1/admin/*', Authorization: Bearer <Clerk JWT>)
          │  (Server-side only, from Server Components / Actions)
          ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │  FastAPI backend — apps/backend/                                 │
 │                                                                  │
 │   routers/admin.py    ──► Depends(require_platform_admin)        │
 │     │                                                            │
 │     ├─ reads: Clerk Backend API + Stripe + DynamoDB +            │
 │     │        OpenClaw gateway RPC + CloudWatch Logs +            │
 │     │        PostHog Persons API                                 │
 │     │                                                            │
 │     └─ writes: @audit_admin_action decorator (fail-closed) →     │
 │               admin_actions_repo.append(...)                     │
 │                                                                  │
 │   core/services/                                                 │
 │     admin_service.py       — composition: aggregate read sources │
 │     admin_audit.py         — @audit_admin_action decorator       │
 │     posthog_admin.py       — PostHog Persons API client          │
 │     cloudwatch_logs.py     — FilterLogEvents wrapper             │
 │     cloudwatch_url.py      — CWL Insights URL builder            │
 │     system_health.py       — /admin/health aggregator            │
 │   core/repositories/                                             │
 │     admin_actions_repo.py  — DDB CRUD                            │
 └──────────────────────────────────────────────────────────────────┘
          │                │               │           │
          ▼                ▼               ▼           ▼
    ┌─────────┐    ┌──────────────┐    ┌──────┐    ┌─────────┐
    │ Clerk   │    │ Stripe       │    │ DDB  │    │ OpenClaw│
    │ Backend │    │ API          │    │ (9   │    │ gateway │
    │ API     │    │              │    │tables│    │ RPC pool│
    └─────────┘    └──────────────┘    └──────┘    └─────────┘

    ┌──────────┐         ┌───────────────────────────────┐
    │ PostHog  │         │ CloudWatch Logs               │
    │ Persons  │         │ (FilterLogEvents inline +     │
    │ API      │         │  Insights deep link)          │
    └──────────┘         └───────────────────────────────┘
```

### Three layers of defense

1. **Edge (Cloudflare Access):** The `admin.isol8.co` hostname is only resolvable / fetchable from someone already authenticated via GitHub/Google SSO with an Isol8-allowlisted email. Configured in the Cloudflare dashboard.
2. **Frontend auth (Next.js middleware + Clerk):** If Cloudflare Access is bypassed somehow, Next.js middleware enforces `host === 'admin.isol8.co'` AND signed-in-via-Clerk. The admin UI calls `GET /admin/me` on mount; a 403 surfaces `/admin/not-authorized`. Unknown hosts requesting `/admin/*` return 404 (default-deny).
3. **Backend auth (`require_platform_admin`):** On every `/api/v1/admin/*` endpoint. A non-admin Clerk-authed user gets `403 Platform admin access required`. This is the real enforcement — edge gates are defense, not authority.

## Auth model — `require_platform_admin` vs `require_org_admin`

A frequent confusion worth stating explicitly:

| Helper | Who qualifies | Purpose |
|---|---|---|
| `require_org_admin` (`core/auth.py:107`) | **Customer** team leads — Clerk `org_role == "org:admin"` in their *own* customer org | Lets a paying customer team lead manage **their own company's** container and billing (e.g. `routers/updates.py`). |
| `require_platform_admin` (`core/auth.py:242`) | **Isol8 employees** — user_id in `PLATFORM_ADMIN_USER_IDS` env var | Gates `admin.isol8.co` and every `/api/v1/admin/*` endpoint. |

The admin router uses `require_platform_admin` exclusively. The structural pattern from `updates.py` (FastAPI router layout, Pydantic request models) is reusable, but its auth model is not.

Admin add/remove in v1 = Secrets Manager edit + backend redeploy. (Phase 2: DDB-backed allowlist with self-service UI.)

## Data model

### DynamoDB — `isol8-{env}-admin-actions`

**Table attributes:**

| Attribute | Type | Required | Purpose |
|---|---|---|---|
| `admin_user_id` (PK) | String | yes | Clerk user ID of the admin taking the action |
| `timestamp_action_id` (SK) | String | yes | `{ISO8601}#{uuidv7}` — sortable by time, unique per action |
| `target_user_id` | String | yes | Clerk user ID of the subject (or `"system"` for fleet-level actions) |
| `action` | String | yes | Dotted action name, e.g. `container.reprovision`, `billing.cancel_subscription` |
| `payload` | Map | yes | Request body as submitted (JSON, redacted of secrets) |
| `result` | String | yes | `success` \| `error` |
| `audit_status` | String | yes | `written` (happy path) \| `panic` (DDB write failed, logged to CloudWatch) |
| `http_status` | Number | yes | Response status code |
| `elapsed_ms` | Number | yes | Server wall-clock time for the handler |
| `error_message` | String | no | Populated when `result=error` |
| `user_agent` | String | yes | Admin browser user agent |
| `ip` | String | yes | Admin client IP (first `X-Forwarded-For` hop from Cloudflare) |

**GSI:** `target-timestamp-index` — PK `target_user_id`, SK `timestamp_action_id`. Answers "show me all actions taken against this user."

**TTL:** none. Audit rows kept forever.

### Audit failure semantics (CEO review S1 — critical)

The audit write is **synchronous before response**, not async post-response. If the DDB write fails:

1. The action's primary effect (Stripe call, ECS reprovision, etc.) has *already* executed — we can't undo it.
2. We log a `panic`-level structured log to CloudWatch with the full action context (admin_user_id, target_user_id, action, payload).
3. The API response includes `audit_status: "panic"` so the UI can warn the operator: "Action succeeded, audit write failed — see CloudWatch for the trail."
4. An alert fires on the `panic` log pattern so operators notice.

This prevents silent audit gaps while accepting that the write completes.

### PostHog Persons API

Backend calls:

```
GET {POSTHOG_HOST}/api/projects/{POSTHOG_PROJECT_ID}/persons/?distinct_id={clerk_user_id}
  Authorization: Bearer {POSTHOG_PROJECT_API_KEY}
```

`distinct_id` is the Clerk `sub`, because `apps/frontend/src/components/PostHogProvider.tsx:51` already calls `posthog.identify(userId, …)` with it.

Deep link to session replay UI: `{POSTHOG_HOST}/replay/{session_id}`.

404 (user never identified) is a legitimate response — v1 surfaces `{events: [], missing: true}` with an explanatory UI banner.

### CloudWatch Logs

Inline viewer calls `logs.FilterLogEvents` with filter pattern:

```
{ $.user_id = "{user_id}" && $.level = "{level}" }
```

Backend emits structured JSON logs with `user_id` and `level` fields (already done via FastAPI middleware). Log group: `/aws/ecs/isol8-{env}-backend` (and Lambda authorizer log groups we want to surface).

**Pagination:** `FilterLogEvents` caps responses at 1 MB / 10k events. The wrapper threads `nextToken` through a `cursor` query param; the UI shows a "Load more" control.

Deep link URL for full search:

```
https://{region}.console.aws.amazon.com/cloudwatch/home?region={region}#logsV2:logs-insights
  ?queryDetail=~(end~'{end_iso}~start~'{start_iso}~timeType~'ABSOLUTE~tz~'UTC
   ~editorString~'fields%20@timestamp%2C%20@message%20%7C%20filter%20user_id%20%3D%20%22{user_id}%22
   ~source~(~'/aws/ecs/isol8-{env}-backend))
```

Pure string assembly, no AWS SDK call from the backend.

## Endpoint surface

All endpoints live under `/api/v1/admin/*`, all decorated with `Depends(require_platform_admin)`.

### Read endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/admin/me` | Who am I, am I an admin — UI gate |
| GET | `/admin/system/health` | Fleet counts, upstream probes, background-task status, recent errors |
| GET | `/admin/actions?target_user_id=&admin_user_id=&action=&limit=&cursor=` | Admin-action audit query (DDB GSI) |
| GET | `/admin/users?q=&plan_tier=&container_status=&cursor=` | Paginated user list (Clerk + DDB join) |
| GET | `/admin/users/{user_id}/overview` | Identity + billing + container + usage |
| GET | `/admin/users/{user_id}/agents?cursor=&limit=` | Agents list via gateway RPC |
| GET | `/admin/users/{user_id}/agents/{agent_id}` | Single agent detail (config + skills + sessions, redacted) |
| GET | `/admin/users/{user_id}/posthog?limit=100` | PostHog person timeline |
| GET | `/admin/users/{user_id}/logs?level=error&hours=24&limit=20&cursor=` | Inline CloudWatch log viewer |
| GET | `/admin/users/{user_id}/cloudwatch-url?start=&end=&level=` | Pre-built CWL Insights deep link |

### Write endpoints — all audited via `@audit_admin_action("...")`

All writes accept an optional `Idempotency-Key` header; server caches `key → response` for 60s to prevent double-submission.

| Method | Path | Action name |
|---|---|---|
| POST | `/admin/users/{user_id}/container/reprovision` | `container.reprovision` |
| POST | `/admin/users/{user_id}/container/stop` | `container.stop` |
| POST | `/admin/users/{user_id}/container/start` | `container.start` |
| POST | `/admin/users/{user_id}/container/resize` | `container.resize` |
| POST | `/admin/users/{user_id}/billing/cancel-subscription` | `billing.cancel_subscription` |
| POST | `/admin/users/{user_id}/billing/pause-subscription` | `billing.pause_subscription` |
| POST | `/admin/users/{user_id}/billing/issue-credit` | `billing.issue_credit` |
| POST | `/admin/users/{user_id}/billing/mark-invoice-resolved` | `billing.mark_invoice_resolved` |
| POST | `/admin/users/{user_id}/account/suspend` | `account.suspend` |
| POST | `/admin/users/{user_id}/account/reactivate` | `account.reactivate` |
| POST | `/admin/users/{user_id}/account/force-signout` | `account.force_signout` |
| POST | `/admin/users/{user_id}/account/resend-verification` | `account.resend_verification` |
| PATCH | `/admin/users/{user_id}/config` | `config.patch` (wraps existing `PATCH /container/config/{owner_id}`) |
| POST | `/admin/users/{user_id}/agents/{agent_id}/delete` | `agent.delete` |
| POST | `/admin/users/{user_id}/agents/{agent_id}/clear-sessions` | `agent.clear_sessions` |

## UI shape

```
apps/frontend/src/
  middleware.ts                    — host-gated (admin.isol8.co ⇒ /admin/*)
  app/
    admin/
      layout.tsx                   — admin-only layout (Home / Users / Health nav)
      page.tsx                     — redirects /admin/users
      not-authorized/page.tsx      — 403 UI for non-platform-admins
      health/
        page.tsx                   — platform health dashboard
      users/
        page.tsx                   — directory (search + table + pagination)
        [id]/
          layout.tsx               — tabs: Overview / Agents / Billing / Container / Activity / Actions
          page.tsx                 — Overview
          agents/
            page.tsx               — agent list
            [agent_id]/page.tsx    — full agent detail
          billing/page.tsx
          container/page.tsx
          activity/page.tsx        — PostHog timeline + deep link
          actions/page.tsx         — audit history for this target
      _actions/                    — Server Actions (writes)
        container.ts               — reprovision, stop, start, resize
        billing.ts                 — cancel, pause, credit, mark-paid
        account.ts                 — suspend, reactivate, force-signout, resend
        config.ts                  — patch
        agent.ts                   — delete, clear-sessions
      _lib/
        api.ts                     — server-only admin API client
        redact.ts                  — mask secrets in openclaw.json before render
  components/
    admin/                         — ESLint boundary: no imports from non-admin code
      ConfirmActionDialog.tsx      — typed-confirmation dialog (client, dynamic-imported)
      CodeBlock.tsx                — syntax-highlighted read-only JSON
      AuditRow.tsx                 — single admin-action audit row
      UserSearchInput.tsx          — search with SWR
      EmptyState.tsx               — reusable empty-state
      ErrorBanner.tsx              — unified error banner (for upstream outages)
      LogRow.tsx                   — expandable log line with full-JSON view
```

**Tab layout (CEO review U2):** 6 tabs — Overview / Agents / Billing / Container / Activity / Actions — with Logs folded into Activity (PostHog + CloudWatch rows on one page). At ≤1200px the tabs collapse to a left sidebar.

## Safety rails

- **Every write endpoint** requires a typed-confirmation dialog on the frontend. "Cancel subscription for `user@example.com`? Type the email below to confirm." 3 wrong attempts locks the dialog; reload required.
- **Every write endpoint** is decorated with `@audit_admin_action("...")`. No path bypasses the audit trail.
- **Secrets never leave the backend.** Admin UI never shows decrypted `user_api_keys` values. It can display "has Anthropic key set: yes / last rotated: 2026-03-17" — nothing more.
- **Config redaction.** `openclaw.json` fields matching `*_key`, `*_secret`, `*_token`, `*_password`, `webhook_url`, `api_key` are replaced with `"***redacted***"` before render.
- **PII viewing is logged.** Loading `/admin/users/{id}/overview` writes an audit row with `action=user.view` (configurable via `ADMIN_AUDIT_VIEWS` env, default on).
- **Idempotency.** All container/billing writes accept an `Idempotency-Key` header to guard against rapid double-submission and two-admin races.
- **Feature flag (`ADMIN_UI_ENABLED`).** Defaults `false`. Per-admin override via `ADMIN_UI_ENABLED_USER_IDS`. Lets ops stage rollout per person.

## Verification strategy

| Layer | Verification |
|---|---|
| Unit | `pytest apps/backend/tests/unit/routers/test_admin.py` — auth gate rejects non-platform-admin; source composition in `admin_service`; audit row written on each action; audit fail-closed path (DDB write error → panic log); timeout wrappers on parallel fetches; CWL pagination; PostHog 404 handling; redaction. |
| Unit (FE) | `pnpm test -- admin` — middleware host-gating (200 on admin.isol8.co, 404 elsewhere); ConfirmActionDialog 3-attempt lockout; EmptyState; LogRow expansion. |
| Integration | Deploy to dev → admin signs into `admin-dev.isol8.co` via Cloudflare Access → sees user directory → loads a test user's overview → fires container.reprovision → confirms audit row in DDB. |
| Security | Non-admin Clerk user → `/admin/me` → expects 403. Logged-out browser → `admin-dev.isol8.co` → expects Cloudflare Access SSO redirect before hitting Vercel. |
| Rollout | `ADMIN_UI_ENABLED=false` → `/admin/*` returns 404. Per-user opt-in via `ADMIN_UI_ENABLED_USER_IDS` verified. |
| E2E | One Playwright spec: sign in as admin → /admin/users → click user → fire read-only action → audit row appears on Actions tab. |

## Local development

| Component | Local behavior |
|---|---|
| Backend `/admin/*` endpoints | Work against LocalStack DDB (`admin-actions` table auto-created by CDK bootstrap) + real dev Clerk/Stripe. |
| `PLATFORM_ADMIN_USER_IDS` | Set in `apps/backend/.env.local` to your dev Clerk user_id. |
| Host gating | `NEXT_PUBLIC_ADMIN_HOST` env (default `admin.isol8.co`) overrideable to `admin.localhost:3000`. Chrome/Safari resolve `*.localhost` → 127.0.0.1 automatically. |
| Cloudflare Access | Production-only. Bypassed entirely for localhost. |
| PostHog | `POSTHOG_PROJECT_API_KEY` unset → `posthog_admin` returns `{events: [], stubbed: true}`. No local failures. |
| CloudWatch Logs | LocalStack Pro emulates CloudWatch Logs — `FilterLogEvents` works against LocalStack if you enable it. Inline viewer shows "LocalStack: no logs" as fallback. |
| Deep link to AWS Console | Points at real AWS. Noted as "dev/prod only" in the UI. |

Full local runbook is in the plan doc, Task 45.

## Rollout

1. Deploy backend with `ADMIN_UI_ENABLED=false` and `PLATFORM_ADMIN_USER_IDS` populated → nothing visible to users.
2. Deploy frontend with admin routes present but 404ing.
3. Add `admin-dev.isol8.co` Cloudflare Access policy; verify SSO works end-to-end.
4. Flip `ADMIN_UI_ENABLED_USER_IDS=<first-admin>` → single admin can access in dev.
5. Exercise the read and write paths manually; confirm audit rows.
6. Repeat for prod (`admin.isol8.co`).
7. Expand `ADMIN_UI_ENABLED_USER_IDS` to the rest of the team.

Rollback: remove `PLATFORM_ADMIN_USER_IDS` → every admin endpoint 403s. DNS alias remains; UI shows not-authorized.

## CEO review findings folded into v1 (summary)

Complete list in the issue; relevant fixes implemented per task in the plan:

- **A1** — middleware default-to-404 on unknown hosts + unit test.
- **A2** — `eslint-plugin-boundaries` pinned with explicit allow/deny config.
- **A3** — Stripe webhook queue depth dropped from `/admin/health` (no log table exists).
- **E1-E5** — error-path handling for Clerk rate-limit, OpenClaw RPC timeout, container-stopped, CWL pagination, PostHog 404.
- **S1** — audit fail-closed: synchronous DDB write, panic log + response flag on failure.
- **S3** — `openclaw.json` secret redaction allowlist.
- **S5** — 3-attempt lockout on typed-confirmation dialog.
- **D1** — `Idempotency-Key` header on container/billing writes.
- **D2** — agents list pagination.
- **D3** — navigate-away behavior: actions continue server-side; audit feed is source of truth.
- **C1** — `admin_service` composes existing services (no duplication).
- **P1/P2** — timeout wrappers on parallel fetches; 30s cache on /admin/health upstream probes.
- **O1** — `admin_api.*` metrics per endpoint.
- **R1/R2** — `ADMIN_UI_ENABLED` feature flag + Cloudflare Access staged-rollout runbook.
- **U1/U2** — empty states + tab layout compression.

## Phase 2 backlog (deferred scope)

1. Correlated activity timeline (admin-actions + PostHog + agent sessions + container events, time-ordered).
2. Impersonation via Clerk `createSignInToken` with dedicated audit trail + TTL.
3. Fleet dashboard (richer than `/admin/health`).
4. Bulk actions (surface existing fleet image update from `updates.py`).
5. Self-service admin add/remove (DDB-backed allowlist).
6. Per-admin rate-limit on write endpoints.
7. 2FA enforcement on platform admins.
8. Correlation IDs threaded through admin actions + downstream Stripe/Clerk/gateway calls.
9. Slack alerts on destructive admin actions.
10. Two-person rule on high-risk actions.
11. Per-user notes field (cross-admin handoff breadcrumbs).
12. `stripe_webhook_log` DDB table (enables webhook queue depth metric).
13. Full custom CloudWatch search UI (replaces AWS Console deep link).
