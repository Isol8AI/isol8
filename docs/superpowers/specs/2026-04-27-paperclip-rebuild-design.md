# Paperclip Rebuild — Design

**Date:** 2026-04-27
**Status:** Validated design; ready for implementation plan
**Supersedes:** PR #186 (`feature/paperclip-integration`, draft) and the addendum at §3.4 of `2026-04-24-flat-fee-byo-llm-claude-credits-design.md`
**Branch:** `feat/paperclip-rebuild`

## 1. Summary

Integrate [Paperclip](https://github.com/paperclipai/paperclip) — an AI agent team
orchestration platform — into Isol8 as a bundled feature available to every
$50 flat-fee user from day one. Users access it at `company.isol8.co`. Their
Paperclip "company" is provisioned on signup, seeded with one agent that mirrors
their main OpenClaw chat agent.

**Key architectural decisions (vs. PR #186 and the addendum):**

1. **Paperclip-as-a-Service**, not per-user sidecar. One shared Paperclip ECS
   task serves the entire fleet via Paperclip's native `companies` multi-tenant
   boundary.
2. **Upstream `paperclipai/paperclip:latest` image, no fork, no patch.**
   Paperclip already supports `DATABASE_URL` as a first-class env var
   (`docs/deploy/database.md`) and ships with `@paperclipai/adapter-openclaw-gateway`,
   so the addendum's "patch DATABASE_URL" assumption was wrong.
3. **Shared Aurora Serverless v2** with `pgvector`, scale-to-zero enabled in
   both dev and prod.
4. **FastAPI backend mediates all `company.isol8.co` traffic.** Paperclip is
   on a private subnet; no public ingress. Single auth surface (Clerk) and
   single brand-rewrite point.
5. **No custom UI.** Paperclip's own UI is served (with light brand-rewrite at
   the proxy) instead of rebuilt — the 15 React panels in PR #186 disappear.
6. **Auth: Board API key per user, Better Auth never used by humans.** Our
   backend mints a per-user Board API key via Paperclip's admin API at
   provisioning time, encrypts it with the existing Fernet `ENCRYPTION_KEY`,
   and injects `Authorization: Bearer <key>` on every proxied request.
   `PAPERCLIP_AUTH_DISABLE_SIGN_UP=true` keeps the public auth surface dead.

**Cost picture:** ~$30–60/mo total fixed cost for the feature (Paperclip task
+ Aurora w/ scale-to-zero across dev + prod), versus the addendum's
+$3.27/user/mo. At spec MAU target (2700), this is ~$0.02/user — roughly two
orders of magnitude cheaper than the addendum's per-user-sidecar model. The
saving comes from eliminating the per-user Fargate memory uplift entirely.

## 2. Why now / what changed

PR #186 (Apr 6, 2026) implemented Paperclip as a tier-gated per-user sidecar
with embedded Postgres. The flat-fee cutover (Apr 24, 2026) killed tiers, and
the addendum at §3.4 of that spec sketched a cheaper rearchitecture assuming
Paperclip needed a `DATABASE_URL` patch and per-user Postgres schemas.

Reading Paperclip's actual deploy docs and source (cloned at `~/Desktop/paperclip`)
invalidates the addendum's premise: Paperclip already has first-class
`DATABASE_URL` support, native multi-tenancy via `companies`, an authenticated
deployment mode with sign-up disable, an instance-admin claim flow, and a
shipping `openclaw-gateway` adapter. The right architecture is dramatically
simpler than either prior proposal.

PR #186 is parked in draft with a comment pointing to this spec. Its
provisioning logic (board API key minting, agent seeding) survives the
architecture change and will be reused; its CDK pro-task-def family, per-user
sidecar, tier gating, and 15 React panels are dropped.

## 3. Architecture

```
┌────────────────────── AWS (us-east-1) ──────────────────────┐
│                                                              │
│   user → company.isol8.co                                    │
│                       │                                      │
│                       ▼                                      │
│              ┌──────────────────────────────┐                │
│              │  ALB                         │                │
│              │  (existing, +1 host rule)    │                │
│              └────────┬───────────┬─────────┘                │
│                       │           │                          │
│        api.isol8.co ──┘           └── company.isol8.co       │
│              │                          (same target group)  │
│              ▼                                  │            │
│   ┌──────────────────┐                          │            │
│   │ FastAPI backend  │◄─────────────────────────┘            │
│   │ (existing)       │                                       │
│   │  + paperclip_    │                                       │
│   │    admin_client  │   admin API   ┌──────────────────┐    │
│   │  + paperclip_    │──────────────▶│ Paperclip server │    │
│   │    proxy router  │  proxied user │ (NEW ECS svc,    │    │
│   │  + paperclip_    │  requests     │  PRIVATE)        │    │
│   │    provisioning  │               │ paperclipai/     │    │
│   └────────┬─────────┘               │ paperclip:latest │    │
│            │                         └─────────┬────────┘    │
│            ▼                                   │             │
│   ┌─────────────────┐               ┌──────────────────┐     │
│   │ DynamoDB        │               │ Aurora Server-   │     │
│   │  + paperclip-   │               │ less v2          │     │
│   │    companies    │               │ + pgvector       │     │
│   │    (NEW)        │               │ scale-to-zero    │     │
│   └─────────────────┘               └──────────────────┘     │
│                                                               │
│   Per-user OpenClaw containers (existing, unchanged)          │
│   Paperclip agents reach them via:                            │
│     wss://ws-{env}.isol8.co  +  Bearer <service-token>        │
│       (token validated by existing Lambda Authorizer)         │
└───────────────────────────────────────────────────────────────┘
```

**Three new pieces of infrastructure:**

1. One Paperclip ECS service (multi-tenant via `companies` table). Single task,
   ~0.5 vCPU / 1 GB to start, autoscale 1–N on CPU. Upstream
   `paperclipai/paperclip:latest`. No fork, no patch, no sidecar.
2. One Aurora Serverless v2 cluster per environment with `pgvector`, min
   ACU = 0 (scale-to-zero), max ACU = 4 to start.
3. One ALB host-rule for `company.isol8.co` → existing FastAPI target group
   (NOT Paperclip's — backend mediates).

**Two new pieces in the existing FastAPI backend:**

1. `paperclip_admin_client` — typed httpx client to Paperclip's admin API for
   company / board-key / agent provisioning.
2. `paperclip_proxy_router` — Clerk-validating reverse proxy at
   `company.isol8.co/*` that injects per-user Board API key and rewrites brand
   strings in HTML responses. Mirrors the existing `control_ui_proxy.py`
   pattern.

**One new DynamoDB table:**

- `isol8-{env}-paperclip-companies`: `user_id` → `{company_id,
  board_api_key_encrypted, service_token_encrypted, status, created_at,
  updated_at, last_error?, scheduled_purge_at?}`. Encrypted with the existing
  Fernet `ENCRYPTION_KEY`.

**Things explicitly NOT in the architecture (vs. PR #186):**

- No per-user Paperclip sidecar.
- No pro/enterprise task definition family.
- No per-user EFS access point for Paperclip (Paperclip uses Aurora, not EFS,
  for its data).
- No tier-aware enable/disable flow (`paperclip_enabled` field deleted with
  the cutover).
- No `/teams` route in the Next.js app.
- No 15 custom React panels — Paperclip's UI fills that role.

## 4. Components

### 4.1 Backend (`apps/backend/`)

| File / Module | Purpose |
|---|---|
| `core/services/paperclip_admin_client.py` | Typed httpx client to Paperclip's admin API. Methods: `create_company(name, owner_email)`, `mint_board_api_key(user_id, company_id)`, `create_agent(company_id, config)`, `disable_user(user_id)`, `delete_company(company_id)`. Auth via instance-admin Board API key from Secrets Manager. Sends `Idempotency-Key: <user_id>` (or scoped variant) on mutations. |
| `core/services/paperclip_provisioning.py` | Orchestrator. On Clerk `user.created` → create Paperclip company → mint Board API key → mint per-user OpenClaw service token → seed main agent with `openclaw-gateway` adapter pre-wired to user's container. Idempotent. Retries via existing `pending-updates` table. |
| `core/repositories/paperclip_repo.py` | DynamoDB repo for new `paperclip-companies` table. Get/put/update/delete by `user_id`. |
| `routers/paperclip_proxy.py` | The `company.isol8.co/*` surface. Host-header dispatch in middleware. Validates Clerk session/cookie, fetches per-user Board API key, forwards to internal Paperclip with `Authorization: Bearer <key>`, streams response. Handles HTTP, WebSocket (live-events), and brand-rewrite (HTML responses only). |
| `routers/webhooks.py` (extend) | Add Paperclip provisioning call to existing Clerk `user.created` / `user.deleted` handlers. |
| `core/config.py` (extend) | New settings: `PAPERCLIP_INTERNAL_URL` (private ECS service URL), `PAPERCLIP_ADMIN_KEY_SECRET_NAME`, `PAPERCLIP_PUBLIC_URL`. |
| `main.py` (extend) | Mount `paperclip_proxy_router` under host-conditional middleware so `Host: company.isol8.co` bypasses the `/api/v1` mount and goes to the proxy. |
| Lambda Authorizer (extend) | Accept service tokens (new long-lived token type) in addition to Clerk JWTs. Service tokens resolve to a `user_id` and route to that user's container. |

### 4.2 Infrastructure (`apps/infra/lib/stacks/`)

| File | Change |
|---|---|
| `database-stack.ts` | **NEW:** Aurora Serverless v2 cluster (`isol8-{env}-paperclip-db`) with `pgvector`, min ACU = 0, max ACU = 4, security group restricting access to backend SG and Paperclip-task SG only. Connection string in Secrets Manager. **NEW table:** `isol8-{env}-paperclip-companies`. |
| `paperclip-stack.ts` (NEW) | ECS Fargate service `isol8-{env}-paperclip-server` running `paperclipai/paperclip:latest`. Env: `DATABASE_URL` (Secrets Manager), `BETTER_AUTH_SECRET` (Secrets Manager), `PAPERCLIP_DEPLOYMENT_MODE=authenticated`, `PAPERCLIP_DEPLOYMENT_EXPOSURE=public` (Paperclip's stricter auth posture for internet-served deployments — independent of network placement; the task itself is on the private subnet behind our backend), `PAPERCLIP_PUBLIC_URL=https://company.isol8.co`, `PAPERCLIP_AUTH_DISABLE_SIGN_UP=true`, `PORT=3100`. Internal-only target group; only backend SG can reach. CloudWatch log group `/isol8/{env}/paperclip`. Autoscaling 1–N on CPU. |
| `paperclip-stack.ts` (NEW) | One-shot ECS task `paperclip-migrate` that runs `drizzle-kit migrate` on deploy. Triggered by CDK custom resource so migrations run before service rollout. |
| `network-stack.ts` | New ALB host rule: `company.isol8.co` → existing FastAPI target group. |
| `dns-stack.ts` | Route 53 A-record for `company.isol8.co` → ALB. ACM cert SAN: add `company.isol8.co` and `company-dev.isol8.co`. |
| `auth-stack.ts` | New secrets: `paperclip/admin-board-key`, `paperclip/better-auth-secret`, `paperclip/database-url`. KMS-encrypted. |

### 4.3 Frontend (`apps/frontend/`)

Tiny surface (the win of using Paperclip's UI as-is):

| File | Change |
|---|---|
| Sidebar / chat header component | Add a "Teams" link/button. Opens `https://company.isol8.co` in the same tab; user is already authenticated via Clerk session cookie scoped to `.isol8.co`. |
| `src/components/onboarding/ProvisioningStepper.tsx` | Optionally surface "Setting up your team workspace" step while Paperclip company provisioning runs (eager webhook → ~2–5 seconds typically). |

No `/teams` route, no Paperclip panel components, no `usePaperclip` hooks.

### 4.4 Auth credentials at rest

| Credential | Storage | Purpose |
|---|---|---|
| Instance admin Board API key | Secrets Manager (`paperclip/admin-board-key`) | Backend uses this to call Paperclip admin API. Minted manually once at deploy. |
| Per-user Board API key | DynamoDB (`paperclip-companies`), Fernet-encrypted | Backend injects as Bearer for that user's proxied requests. |
| Per-user OpenClaw service token | DynamoDB (`paperclip-companies`), Fernet-encrypted | Baked into seeded Paperclip agent's `openclaw-gateway` adapter config. Long-lived JWT signed by us (not Clerk), claims include `sub=user_id` + `kind=paperclip_service`. Validated by the extended Lambda Authorizer alongside Clerk JWTs. |

## 5. Data Flow

### 5.1 Signup → company provisioned

```
Clerk: user.created webhook
    │
    ▼
FastAPI: /webhooks/clerk
    │
    ├─→ existing user creation (DynamoDB users table)
    │
    └─→ paperclip_provisioning.provision(user_id, email)
            │
            ├─ 1. paperclip_admin_client.create_company(name=email, owner_email=email)
            │       └─ returns company_id
            │
            ├─ 2. paperclip_admin_client.mint_board_api_key(user_id, company_id)
            │       └─ returns board_key (one-shot reveal)
            │
            ├─ 3. mint_openclaw_service_token(user_id)  (long-lived, Lambda-Authorizer-validated)
            │
            ├─ 4. paperclip_admin_client.create_agent(company_id, config={
            │       name: "Main Agent",
            │       adapter: "openclaw-gateway",
            │       adapter_config: {
            │         url: "wss://ws-{env}.isol8.co",
            │         authToken: <openclaw_service_token>,
            │         sessionKeyStrategy: "fixed",
            │         sessionKey: user_id
            │       }
            │     })
            │
            └─ 5. paperclip_repo.put({
                  user_id, company_id,
                  board_api_key_encrypted: fernet(board_key),
                  service_token_encrypted: fernet(svc_token),
                  status: "active"
                })
```

Whole flow runs synchronously in the webhook handler. On failure, webhook returns 5xx so Clerk retries; if exhausted, fall back to enqueue in `pending-updates`. Idempotent on `user_id` (existing row → no-op).

### 5.2 User clicks "Teams" → Paperclip UI loads

```
Browser: GET https://company.isol8.co/
   ├─ Cookie: __session=<clerk-jwt>  (already set on .isol8.co by main app)
   │
   ▼
ALB: host rule company.isol8.co → FastAPI target group
   │
   ▼
FastAPI middleware: Host=company.isol8.co → paperclip_proxy_router
   │
   ├─ validate Clerk JWT (existing get_current_user)
   ├─ paperclip_repo.get(user_id) → board_api_key (decrypted)
   │
   ▼
httpx.AsyncClient: GET {PAPERCLIP_INTERNAL_URL}/
   Headers: Authorization: Bearer <board_api_key>
            X-Forwarded-Host: company.isol8.co
            X-Forwarded-Proto: https
   │
   ▼
Paperclip server: returns SPA HTML
   │
   ▼
FastAPI proxy: brand-rewrite pass on HTML
   ├─ <title>Paperclip</title> → <title>Isol8 Teams</title>
   ├─ og:* meta tags → Isol8 equivalents
   └─ stream response back to browser
```

WebSocket flow (Paperclip live-events): browser opens `wss://company.isol8.co/api/live`. FastAPI accepts the WS upgrade, opens a parallel WS to `{PAPERCLIP_INTERNAL_URL}/api/live` with `Authorization: Bearer`, bidirectionally relays frames. Same shape as `control_ui_proxy.py`'s WS relay.

### 5.3 Paperclip agent run → user's OpenClaw container

```
Paperclip server: agent wakes (cron / approval / manual trigger)
   │
   ├─ loads agent config: adapter=openclaw-gateway,
   │   url=wss://ws-{env}.isol8.co,
   │   authToken=<service_token>, sessionKey=<user_id>
   │
   ▼
@paperclipai/adapter-openclaw-gateway: WebSocket to ws-{env}.isol8.co
   │
   ▼
Lambda Authorizer (extended): accepts service tokens AND Clerk JWTs
   ├─ resolves user_id from token, attaches to connection context
   │
   ▼
API GW $connect → DynamoDB ws-connections table
   │
   ▼
agent.connect / agent.run frames → existing FastAPI ws/message endpoint
   → existing GatewayConnectionPool → user's OpenClaw container
   │
   ▼
Stream events → Management API → Paperclip's adapter (same path as today's chat)
```

Key insight: Paperclip agents reuse the existing OpenClaw gateway WebSocket entrypoint. No new ingress, no new auth path — just a new token type the existing Lambda Authorizer recognizes. The user's OpenClaw container doesn't even know whether the caller is the chat UI or a Paperclip agent.

### 5.4 Subscription cancellation / account deletion → cleanup

Two distinct triggers, both flow into the same `disable` path:

- **Stripe `customer.subscription.deleted` (or `.canceled`)** — paying user cancels. They lose product access but keep their Clerk account. Paperclip company gets disabled with a 30-day grace.
- **Clerk `user.deleted`** — account-level deletion (rare). Same disable path, also 30-day grace.

```
trigger webhook (Stripe or Clerk)
   │
   ▼
FastAPI: /webhooks/stripe or /webhooks/clerk
   │
   └─→ paperclip_provisioning.disable(user_id)
         ├─ paperclip_admin_client.disable_user(user_id) → revokes board key,
         │   marks company "disabled" in Paperclip
         ├─ paperclip_repo.update(status="disabled", scheduled_purge_at=now+30d)
         └─ revoke_openclaw_service_token(user_id)

Cron job (existing pending-updates worker, extend):
   ├─ once/day, scan paperclip_repo where scheduled_purge_at < now
   ├─ paperclip_admin_client.delete_company(company_id) → hard delete
   └─ paperclip_repo.delete(user_id)
```

30-day grace matches our existing data-retention posture for billing changes.
Re-subscription within the grace window restores access (provisioning is
idempotent on `user_id`).

### 5.5 Failure & retry

Three failure modes for provisioning:

1. **Paperclip server down at signup** → admin client throws, webhook returns 5xx, Clerk retries (exponential backoff up to ~24 hr). If still failing, fall back to inserting row in `pending-updates` table with `kind=paperclip_provision`, picked up by existing scheduled worker.
2. **Partial completion** (company created, key minting failed) → idempotency: each step checks for existing artifacts before re-creating. Re-run is safe.
3. **Failed status surfaces to user**: if `paperclip_repo.get(user_id).status == "failed"`, the proxy returns a friendly 503 page ("Your team workspace is being set up — refresh in a moment"), and a backend cron retries provisioning.

## 6. Error Handling

| Failure | Detection | Response |
|---|---|---|
| Paperclip server returns 5xx | proxy gets non-2xx upstream | Pass through 502 with branded error page; CloudWatch alarm if rate > 5%/5min |
| Aurora cold-start (scale-to-zero waking) | first request after idle takes ~10–15s | Proxy timeout = 30s on first request, 10s on warm requests; Paperclip's own connection pool handles retries |
| Per-user board key invalid / decryption fails | Fernet raises, or Paperclip returns 401 | Mark `paperclip-companies.status=failed`, enqueue re-provision in `pending-updates`, return branded 503 to user |
| Brand-rewrite breaks HTML (upstream changes structure) | Response no longer parseable as HTML, or content-type isn't HTML | Fail open — pass response through unmodified rather than corrupt it. Log warning. (Cosmetic regression > broken UI) |
| Service token rejected by Lambda Authorizer | OpenClaw WS connection refused inside Paperclip agent run | Paperclip's adapter retries once with stored token; if still rejected, surface as agent run failure. Backend cron detects `auth_failed` events and re-mints. |
| WebSocket relay disconnect | either side closes | FastAPI tears down the paired socket. Browser side reconnects via Paperclip's existing reconnect logic. No state loss because Paperclip is the source of truth. |
| Clerk JWT expired mid-session | proxy gets 401 from `get_current_user` | Return 401 to browser; existing Clerk client refreshes and retries — same as the rest of the app |
| Aurora unreachable (network blip) | Paperclip server's own DB pool errors | Paperclip's own behavior dominates here — likely returns 5xx for affected requests. Our proxy passes them through. CloudWatch alarm on Aurora `DatabaseConnectionAttempts` failures. |

**Cross-cutting:**

- **Circuit breaker on the proxy** — if upstream Paperclip 5xx rate > 50% in 30s window, short-circuit to a static "Teams temporarily unavailable" page for 60s. Prevents thundering-herd against a struggling Paperclip server.
- **Idempotency keys** on admin API mutations from `paperclip_admin_client` — pass `user_id` as the key for company creation, `user_id:agent` for agent seeding.
- **Observability** — every proxied request gets a correlation ID propagated as `x-correlation-id` (already standard on backend per existing `e2e_correlation.py`).

## 7. Testing

| Layer | Test | Tool |
|---|---|---|
| Unit | `paperclip_admin_client` against an httpx `MockTransport` — request shape, idempotency keys, error mapping | pytest |
| Unit | `paperclip_provisioning.provision()` — idempotency on re-run, partial-completion recovery, fernet round-trip on stored keys | pytest |
| Unit | `paperclip_proxy_router` brand-rewrite — given known Paperclip HTML fixtures, verifies title/og rewrites, fail-open on malformed input | pytest |
| Unit | Lambda Authorizer extension — service token validation accepts known-good token, rejects forged/expired | pytest, moto for KMS |
| Integration | Local-stack: spin up real Paperclip container against an embedded Postgres, hit it through the proxy router, assert end-to-end auth path works | docker-compose in CI |
| Integration | Provisioning round-trip on local-stack: simulate Clerk webhook → assert company exists in Paperclip + DynamoDB row written + agent created with correct adapter config | docker-compose |
| E2E | Playwright: signed-in user navigates from `/chat` to `company.isol8.co`, sees Paperclip UI, can list agents, agent appears with `openclaw-gateway` adapter pointing at correct URL | extend existing E2E suite |
| E2E | Paperclip agent triggers OpenClaw chat → assert message reaches user's container and response streams back through the standard WebSocket chat path | dev environment |
| Smoke | On every deploy: `GET company.isol8.co/api/health` → 200; `GET company.isol8.co/` returns brand-rewritten HTML; one provisioned test user can log in | existing smoke-test workflow |
| Migration | Drizzle migrations run cleanly on a fresh Aurora cluster (CI step before deploy) | `drizzle-kit migrate --dry-run` |

**Out of scope for v1 testing:**

- Load testing (defer to first scale event).
- Chaos testing (circuit breaker covers the main case).
- Cross-company isolation regression tests — relying on Paperclip's own multi-tenant test suite.

## 8. Open questions for implementation

These are not architectural unknowns but verification steps for the plan:

1. **Confirm Paperclip's admin API surface.** Verify endpoints exist (or how to use Better Auth admin SDK server-to-server) for: company creation, board API key minting for a given user, agent creation with adapter config, user/company disable + delete. PR #186's `provision_paperclip_board_key` was implemented but never proven against a live Paperclip server end-to-end (its Backend CI was failing on the latest commit). Treat as discovery, not assumed-working.
2. **Confirm `openclaw-gateway` adapter accepts dynamic `authToken` per-agent** (the README implies yes). Test with a manually-created Paperclip company before automating.
3. **Confirm Aurora Serverless v2 with `pgvector`** in our region (us-east-1) — should be GA but worth a one-line CDK validation.
4. **Decide service-token format and TTL.** Probably reuse our existing JWT-signing infra with a long expiry (e.g., 1 year, rotatable). This also drives the Lambda Authorizer extension shape.

## 9. Out of scope for v1

- Custom Isol8-branded React UI for Paperclip features (keeps Paperclip's UI, with proxy-level brand-rewrite only).
- Annual / discount pricing for Paperclip-included tier.
- Cross-company collaboration (Paperclip supports it; we don't expose it).
- Multi-org per Isol8 user (single-org-per-user is invariant per `project_single_org_per_user` memory).
- Mobile-app access to Paperclip.
- Custom domain support (users on `*.isol8.co` only for v1).

## 10. References

- `docs/superpowers/specs/2026-04-24-flat-fee-byo-llm-claude-credits-design.md` — flat-fee cutover spec; addendum at §3.4 superseded by this spec.
- `docs/superpowers/specs/2026-04-05-paperclip-integration-design.md` — original design for PR #186 (per-user sidecar). Reference only.
- PR #186: <https://github.com/Isol8AI/isol8/pull/186> — parked in draft.
- Paperclip upstream: <https://github.com/paperclipai/paperclip>. Local checkout: `~/Desktop/paperclip`.
- Paperclip deploy docs: `docs/deploy/database.md`, `docs/deploy/aws-ecs.md`, `docs/deploy/environment-variables.md`.
- Paperclip OpenClaw adapter: `packages/adapters/openclaw-gateway/README.md`.
- `apps/backend/routers/control_ui_proxy.py` — existing proxy pattern to copy.
- `apps/backend/core/encryption.py` — existing Fernet wrapper for credential encryption.
- `apps/backend/core/repositories/api_key_repo.py` — existing pattern for encrypted credential storage.
