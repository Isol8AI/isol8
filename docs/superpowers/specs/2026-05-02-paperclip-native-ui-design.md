# Paperclip Native UI — Design

**Date:** 2026-05-02
**Status:** Validated design; ready for implementation plan
**Supersedes:** Decision #5 of `2026-04-27-paperclip-rebuild-design.md` (*"No custom UI. Paperclip's own UI is served (with light brand-rewrite at the proxy) instead of rebuilt"*)
**Branch:** `feat/paperclip-native-ui` (proposed)

## 1. Summary

Replace `dev.company.isol8.co` (transparent reverse proxy of upstream Paperclip's own UI) with a native React UI inside the existing Isol8 Next.js app at `dev.isol8.co/teams/*`. All Paperclip access goes through a thin FastAPI BFF that wraps Paperclip's REST API server-side; the browser never talks to Paperclip directly.

**Why we're reversing the 2026-04-27 "no custom UI" decision:**

1. **Cross-cutting hardening tail.** The transparent proxy has produced an open-ended list of cross-domain integration concerns: cookie-domain rewrite, `__t=` JWT-in-URL handoff, brand string rewrite, Origin/CSRF defenses, single-sign-in flow, circuit breaker. Each exists *because we're proxying a UI we don't control*. They go away the moment the proxy goes away.
2. **Active code-execution exploit (audit at `.tmp-paperclip-audit/route-audit.md`).** Through the transparent proxy, any signed-in tenant can hit `POST /api/companies/:id/agents` with `{"name":"x"}` and create a `process`-adapter agent (shell exec on the shared container, which holds Aurora master credentials). The `openclaw_gateway` adapter has SSRF via `adapterConfig.url`. Indirect adapterType carriers exist in approvals, invite-accept, and company-import. Pre-existing DDB rows can replay non-gateway adapter types via approve/rollback. Filter-by-route on the proxy is whack-a-mole — 124 routes catalogued, 24 BLOCK, 8 FILTER_REQUEST, 1 FILTER_RESPONSE, plus a startup data sweep.
3. **The native-UI architecture closes all of (2) by construction.** The browser never names `adapterType` (we always submit `openclaw_gateway`), never names a URL (BFF synthesizes from the org's container row), never reaches `/api/companies/import` or invite-accept (we don't expose them). The BFF is a finite, auditable surface; the proxy filter is enumerating an attack surface we don't own.

**What changes architecturally:**

- One Vercel domain (`dev.isol8.co`); `dev.company.isol8.co` retired with a 301 → `/teams`.
- FastAPI BFF endpoints under `/api/v1/teams/*` make scoped calls to Paperclip using a hybrid auth model: admin session for admin-only ops, per-user Better Auth session for user-scoped ops.
- 1494-line `paperclip_proxy.py`, brand rewrite, cookie domain rewrite, `__t=` handoff JS, the Better Auth session-cookie forwarding model — all deleted at the end of the migration.

**What stays the same:**

- The `paperclip-companies` DDB table schema, including `paperclip_password_encrypted` and `service_token_encrypted`. The password's role changes from "credential the proxy forwards as a cookie" to "credential the BFF uses for backend-side sign-in" — same secret, different consumer.
- `paperclip_admin_session.py`, `paperclip_admin_client.py`, `paperclip_provisioning.py`, `paperclip_repo.py`. All four are reused as-is or extended.
- Upstream Paperclip image — no fork, no patch.

## 2. Architecture

```
Browser                Vercel/Next.js          FastAPI Backend            Paperclip
  /teams/*  -- HTTPS --> Next.js App      -- HTTPS -->  BFF       -- HTTPS --> upstream
                        (Clerk session)              (admin OR user
                                                     Paperclip session)
```

### Layering

1. **Browser**: Clerk-authenticated session on `dev.isol8.co`. No Paperclip cookies, no cross-domain handoff. Client uses SWR + `useApi()` to call the Isol8 BFF. Same auth surface as `/chat`.
2. **Next.js (`apps/frontend`)**: native React routes under `/teams/*` mirroring the existing OpenClaw control-panel pattern in `apps/frontend/src/components/control/`. Each panel is a server-or-client React component pair calling the BFF.
3. **FastAPI BFF (`apps/backend/routers/teams/`)**: receives `Authorization: Bearer <Clerk JWT>`, validates via `get_current_user`, resolves `owner_id` via existing `resolve_owner_id` helper, reads the `paperclip-companies` row to find `company_id`, makes scoped Paperclip REST calls.
4. **Paperclip**: unchanged upstream. Authz enforced server-side via `req.actor.userId` and `req.actor.companyMemberships`.

### URL & domain consolidation

| Surface | Before | After |
|---|---|---|
| Tenant UI | `dev.company.isol8.co/*` (proxied Paperclip UI) | `dev.isol8.co/teams/*` (native React) |
| Tenant API | `dev.company.isol8.co/api/*` (proxied) | `dev.isol8.co/api/v1/teams/*` (BFF) |
| Cookie scope | `.isol8.co` (forced rewrite) | `dev.isol8.co` only (Clerk default) |
| Cross-domain JWT handoff | `?__t=` query param | None |
| Brand rewrite | `<title>` + `og:site_name` HTML rewrite | Native React renders Isol8 branding |

`dev.company.isol8.co` retires with a 301 to the matching `/teams` path. Vercel removes the `company.` subdomain rewrite. The `dev.company.isol8.co` ACM cert and DNS record retire after a deprecation window.

### Auth model: hybrid (admin + per-user Better Auth session)

Two distinct authentication pathways into Paperclip from the BFF, used for different operations.

**Admin session** (existing, `apps/backend/core/services/paperclip_admin_session.py`):
- Used for admin-only operations — `POST /api/companies` (create-company), `POST /api/companies/:co/invites` (mint invite), `POST /api/companies/:co/join-requests/:rid/approve` (auto-approve), `POST /api/companies/:co/members/:mid/archive` (member archive on Clerk-leave).
- Session cookie cached in-process, refreshed on 401 via the existing `invalidate_admin_session()` retry.
- Backed by the bootstrapped `admin@isol8.co` instance-admin account.

**Better Auth sign-up is not actor-typed admin.** `POST /api/auth/sign-up/email` is the standard Better Auth route, gated by the library's own `disableSignUp` flag (`paperclip/server/src/auth/better-auth.ts:121`). Production keeps `PAPERCLIP_AUTH_DISABLE_SIGN_UP=false` and relies on **network-level closure** (Paperclip is on a private subnet, reachable only through our backend) — see the docstring at `apps/backend/core/services/paperclip_admin_client.py:75-88`. The BFF calls sign-up unauthenticated from inside the VPC at provisioning time. Sign-in is the same shape (`POST /api/auth/sign-in/email`) and returns the user-scoped session cookie.

**Per-user Better Auth session** (new, `apps/backend/core/services/paperclip_user_session.py`):
- Used for **every read/write the user makes on their own company** — list agents, create agent, view runs, mark issues, all of it.
- BFF reads the user's `paperclip-companies` row, decrypts `paperclip_password_encrypted`, signs in via Better Auth (`POST /api/auth/sign-in/email`), captures the `Set-Cookie`. Session cookie kept in the BFF process. **Never forwarded to the browser.**
- V1: per-request sign-in (~ms inside VPC; matches the existing proxy's behavior).
- V2: short-TTL in-process or Redis cache keyed by `user_id`, refreshed on 401. Mirrors `paperclip_admin_session.py` shape.

**Why hybrid:** Paperclip's authz model uses `req.actor.userId` and `req.actor.companyMemberships` to enforce tenant isolation on every API call (`paperclip/server/src/middleware/auth.ts`). If the BFF has a scoping bug — forgets to check `company_id`, leaks a user-id parameter, etc. — the user's session physically cannot see another tenant's data because Paperclip filters server-side. Admin compromise is contained to admin-only operations.

**Why we don't use Board API keys (corrected from earlier brainstorm):** Paperclip's REST surface has no admin endpoint to mint a Board API key for a user. The only mint path is the CLI auth challenge flow (`paperclip/server/src/services/board-auth.ts:280-294`) which requires a logged-in-user approval over an authenticated session. Direct DB insert into `boardApiKeys` would work technically (we own the Aurora) but ties us to upstream schema details. The Better Auth sign-in path is documented and stable.

**Why we don't drop `paperclip_password_encrypted`:** the existing field is the mechanism by which our BFF can act as the user. The proxy forwarded the resulting cookie to the browser; the native UI keeps it backend-side. Same secret, different consumer.

## 3. Tenancy

**One Clerk org → one OpenClaw container → one Paperclip company → multiple Isol8 user members.**

This mirrors the existing OpenClaw model (`apps/backend/core/auth.py:97-99`):

```python
def resolve_owner_id(auth: AuthContext) -> str:
    """Return the container/workspace owner: org_id if in org, else user_id."""
    return auth.org_id if auth.is_org_context else auth.user_id
```

- Container ownership: `owner_id = org_id` when in org context, else `user_id`. All members of an Isol8 Clerk org share the same OpenClaw container.
- Paperclip company ownership: same shape. The `paperclip-companies` table already supports it: PK is `user_id` (per-user row), but `company_id` is shared across all rows in the same Clerk org, with a `by-org-id` GSI for lookup (existing).
- Each org member has their own Better Auth account inside Paperclip (`paperclip_user_id`). Acting under their own session preserves created-by attribution everywhere automatically (Alice creates an issue → Paperclip records Alice's `userId` → Bob sees "Created by Alice").

### Provisioning fan-out

Three cases, all driven by Clerk webhooks (`user.created`, `organizationMembership.created`, `organizationMembership.deleted`) plus the existing `POST /api/v1/users/sync` idempotent endpoint.

**Case A — first user creating org / first user joining brand-new org:**
1. Admin session calls `signUp` to create Better Auth account for the user.
2. Admin session calls `create-company` with the user as company *owner*.
3. Admin session creates the seeded openclaw_gateway agent. Adapter URL = org container's gateway URL; token = the user's freshly-issued OpenClaw service-token JWT.
4. DDB row written with all fields.

**Case B — subsequent user joining existing org** (`organizationMembership.created`):
1. Admin session calls `paperclip_repo.get_org_company_id(org_id)` via the `by-org-id` GSI → returns the shared `company_id`.
2. Admin session calls `signUp` to create Better Auth account for the new user.
3. Admin session calls `create-invite` for the existing company.
4. Admin session calls `approve-join-request` (auto-approve; we own membership).
5. DDB row written with the same `company_id`.

No user-side click. The user opens `/teams` and is immediately a member.

**Case C — member leaves org** (`organizationMembership.deleted`):
1. Admin session looks up the leaver's company-membership row id (via `GET /api/companies/:co/members`, find row whose `principalId == paperclip_user_id`).
2. Admin session calls `POST /api/companies/:co/members/:memberId/archive` (per `paperclip/server/src/routes/access.ts:4231`).
3. DDB row marked `status=disabled`, scheduled for purge after the existing `scheduled_purge_at` window.
4. Better Auth account stays (so audit references like "Created by Alice" continue to resolve). Agents continue working — they point at the org's shared container, no rebinding needed.

## 4. Panel inventory

### Tier 1 — MVP (ship in this design)

| Route | Description | Paperclip routes consumed |
|---|---|---|
| `/teams` | Dashboard / overview metrics | `dashboard`, `sidebar-badges` |
| `/teams/agents` | Agent list (filtered to org's company) | `agents` |
| `/teams/agents/new` | Agent create form. `adapterType` locked to `openclaw_gateway`; URL + token synthesized server-side from the org's `containers` row. | `agents` (POST) |
| `/teams/agents/:id` | Agent detail (overview / runs / config / skills / budget tabs) | `agents`, `runs` |
| `/teams/agents/:id/runs/:runId` | Run transcript | `runs` |
| `/teams/inbox` | Notifications, failed runs, pending approvals | `inbox`, `approvals`, `inbox-dismissals` |
| `/teams/approvals` | Approval cards | `approvals` |
| `/teams/issues` | Issue list / kanban | `issues`, `issue-tree-control` |
| `/teams/issues/:id` | Issue detail | `issues` |
| `/teams/routines` | Cron-scheduled recurring tasks | `routines` |
| `/teams/goals` | Hierarchical goal tree | `goals` |
| `/teams/projects` | Project list | `projects` |
| `/teams/projects/:id` | Project detail (overview / issues / budget) | `projects` |
| `/teams/activity` | Audit feed | `activity` |
| `/teams/costs` | Read-only cost analytics (informational; does not replace Isol8 billing) | `costs` |
| `/teams/skills` | Read-only skill browse (no upload, no sync) | `company-skills` |
| `/teams/members` | Read-only member list (mirrors Clerk org). No invite/remove actions. | derived from `companyMemberships` + Clerk |
| `/teams/settings` | Tenant-safe company settings (display name; default model dial that maps to OpenClaw config). No instance-level options. | `companies` (PATCH whitelist) |

Sidebar prefs (`sidebar-preferences`) and inbox-dismissals are surfaced inline within their relevant panels rather than as separate routes.

### Tier 3 — explicitly deferred to v2+

- **Org chart visualization** (`org-chart-svg`) — useful but non-trivial; defer.
- **Skills upload + OpenClaw↔Paperclip skill sync** — overlaps with OpenClaw skills; v2 unification problem.
- **Members invite/remove** — Clerk-owned. Surfaced in Clerk's existing flows, not in `/teams`.
- **Secrets store** (`secrets`) — overlaps with Isol8 BYOK (`api_key_repo`). Don't expose.
- **Environments / environment-selection** — advanced multi-environment workflow. Not needed v1.
- **LLM provider config** (`llms`) — model selection happens in OpenClaw config, not Paperclip's.
- **User profile** (`user-profiles`) — Clerk-owned identity. No Paperclip profile editing.

### Tier 4 — explicitly blocked from tenant UI (operator-only or dangerous)

Not exposed at `/teams/*`. If ever needed, surface behind a separate `admin.isol8.co/paperclip` iframe gated by the existing admin-host middleware (`decideAdminHostRouting` in `apps/frontend/src/middleware.ts`):

- Adapter management (`adapters`)
- Plugins (`plugins`, `plugin-ui-static`)
- Instance settings (`instance-settings`)
- Instance database backups (`instance-database-backups`)
- Access admin (`access` admin endpoints, claim-instance-admin, role grants)
- Company import / portability (`/api/companies/import` — adapterType bypass route per audit §3)
- Environment management (`environments`, `environment-selection`)

## 5. Backend BFF surface

Routers split for clarity, all under `apps/backend/routers/teams/`:

```
apps/backend/routers/teams/
  __init__.py        # router registration
  agents.py          # agents + runs
  inbox.py           # inbox + approvals + dismissals
  issues.py          # issues + issue-tree-control
  projects.py        # projects + goals + routines
  activity.py        # activity + costs + dashboard
  members.py         # members read-only
  settings.py        # company settings (tenant-safe subset)
  skills.py          # company-skills read-only
```

Mounted under `/api/v1/teams/*`.

### Endpoint pattern

Every endpoint follows the same shape:

```python
@router.post("/agents")
async def create_agent(
    body: CreateAgentRequest,         # whitelisted Pydantic schema, no adapterType
    auth: AuthContext = Depends(get_current_user),
):
    owner_id = resolve_owner_id(auth)
    company = await paperclip_repo.get(auth.user_id)
    if not company:
        raise HTTPException(409, "team workspace not provisioned")

    container = await container_repo.get_by_owner_id(owner_id)
    if not container:
        raise HTTPException(503, "container offline")

    # SECURITY: synthesize adapter block server-side. Never accept from client.
    adapter_config = synthesize_openclaw_adapter(
        gateway_url=container["gateway_url"],
        service_token=decrypt(company.service_token_encrypted),
        user_id=auth.user_id,
    )

    upstream_body = {
        "name": body.name,
        "role": body.role,                    # Paperclip requires role (e.g. "ceo", "engineer")
        "adapterType": "openclaw_gateway",    # underscore — canonical per packages/shared/src/constants.ts:40
        "adapterConfig": adapter_config,
    }

    session = await paperclip_user_session.get_user_session_cookie(auth.user_id, http_client)
    return await paperclip_call(
        method="POST",
        path=f"/api/companies/{company.company_id}/agents",
        json=upstream_body,
        cookie=session,
    )
```

### Adapter-config synthesis (the security hotspot)

`synthesize_openclaw_adapter()` lives in `apps/backend/core/services/paperclip_adapter_config.py`. Rules:

1. `adapterType` is hardcoded to `"openclaw_gateway"` (underscore — per `paperclip/packages/shared/src/constants.ts:40`). **Note:** existing `paperclip_provisioning.py:255` sends `"openclaw-gateway"` (hyphen) — a real production bug; the seed-agent creation has been silently failing because `assertKnownAdapterType` rejects the hyphenated value, swallowed by the existing try/except at `paperclip_provisioning.py:265-270`. Phase 1 fixes this alongside the BFF rewrite.
2. The synthesized `adapterConfig` is exactly:
   ```json
   {
     "url": "<validated_gateway_url>",
     "authToken": "<decrypted_service_token>",
     "sessionKeyStrategy": "fixed",
     "sessionKey": "<auth.user_id>"
   }
   ```
   Field name is `authToken`, not `token` (per `paperclip/packages/adapters/openclaw-gateway/src/index.ts:21` and the existing production shape at `paperclip_provisioning.py:256-261`). No `headers`, no other adapter fields.
3. `url` comes from `containers.gateway_url` for the resolved `owner_id`. Validated against an allowlist regex pinned to internal hostnames (confirm exact format in implementation plan against `core/containers/ecs_manager.py` or `core/gateway/connection_pool.py`). Any URL not matching → 500 (operator bug, not user input).
4. `authToken` comes from decrypting `service_token_encrypted` for that user.
5. Every BFF endpoint that creates or patches an agent calls this function. Any path that accepts `adapterType`, `adapterConfig`, or any field path containing those *from the client* fails Pydantic validation (whitelist schema, not blacklist).

### Other invariants enforced by the BFF

- **No `/api/companies/import` ever exposed.** The whole route surface is unreachable through the BFF.
- **Approvals never carry adapterType in payload.** BFF whitelist on approval-create / approval-resubmit bodies.
- **Invite-accept never reachable from tenant UI.** Membership flows are admin-driven via Clerk webhooks; tenants never POST to invite-accept paths.

## 6. Data model

### `paperclip-companies` (existing DDB table) — schema unchanged

| Column | Purpose | Change |
|---|---|---|
| `user_id` (PK) | Per-Isol8-user row | unchanged |
| `org_id` | Clerk org id (shared across rows in same org) | unchanged |
| `company_id` | Paperclip company id (shared across rows in same org) | unchanged |
| `paperclip_user_id` | Better Auth user id | unchanged |
| `paperclip_password_encrypted` | Fernet-encrypted Better Auth password | **kept**; consumer changes from proxy → BFF user-session |
| `service_token_encrypted` | Fernet-encrypted OpenClaw service-token JWT | unchanged |
| `status`, `created_at`, `updated_at`, `last_error`, `scheduled_purge_at` | Existing | unchanged |

GSIs: `by-org-id`, `by-status-purge-at` — unchanged.

No new tables. No CDK schema migration.

### `containers` (existing) — read-only access

BFF reads `gateway_url` and resolves the org/personal context to find the container. No schema change.

## 7. Provisioning

The existing `paperclip_provisioning.py` flow extends to handle the org-vs-personal split:

1. **`POST /api/v1/users/sync`** (existing, idempotent): on first call, creates the user's Paperclip company + Better Auth account if not present. Detects org context via `auth.org_id`; calls `get_org_company_id` to decide create-vs-join.
2. **Clerk webhooks** (extended in `apps/backend/routers/webhooks.py`):
   - `user.created` — no-op for Paperclip (provisioning happens on first `/api/v1/users/sync`).
   - `organizationMembership.created` — Case B fan-out: lookup existing `company_id`, signUp + invite + approve.
   - `organizationMembership.deleted` — Case C fan-out: deactivate membership, mark DDB row disabled.
3. **No lazy-on-first-`/teams`-visit path.** The 1:1 invariant ("every user with an OpenClaw container has a Paperclip company") is maintained at provisioning time, not deferred.

A user opens `/teams` while their company is still mid-provisioning (rare; webhook-driven) → BFF returns 202 with `{ status: "provisioning" }`. The UI shows the same "still setting up" stub the OpenClaw onboarding flow uses today and polls.

## 8. Migration

### Phase 0 (separate PR; ships first; not blocked by this design): proxy stopgap

Per the audit findings, the proxy is exploitable today on the active company `co_d0f4f7ca`. Before this design's Phase 1 lands, ship a defense-in-depth deny-by-default filter at `paperclip_proxy.py`:

- Hard-allowlist the ~10 read-only routes a tenant uses in normal operation. Everything else 403.
- Defense-in-depth: pre-write `${PAPERCLIP_HOME}/adapter-settings.json` at provisioning to disable the 10 dangerous builtin adapters in the UI (per audit §4 — UI/discovery hardening only, not a security gate).
- Hide the "Teams" entrypoint button behind a feature flag for prod users to prevent additional accounts from reaching the exploitable path.

This is a one-PR stopgap, not part of this design's implementation work.

### Phase 1 (this design): native UI MVP

- Build `/teams/*` panel set in `apps/frontend` per §4.
- Build `/api/v1/teams/*` BFF in `apps/backend` per §5.
- Add `paperclip_user_session.py`.
- Behind a Next.js middleware feature flag (`teamsNativeUiEnabled`); default on for dev, off for prod.
- Both proxy and native UI live in parallel during testing. Hand-test on dev with the existing `co_d0f4f7ca` company (already provisioned, validates that no DDB schema migration is needed).

### Phase 2: cutover

- Flip `teamsNativeUiEnabled` on for prod.
- 301 `dev.company.isol8.co/*` → `dev.isol8.co/teams/*` matching path.
- Vercel removes the `company.` subdomain rewrite.

### Phase 3: cleanup

- Delete `apps/backend/routers/paperclip_proxy.py` (~1494 lines).
- Delete cookie-domain rewrite, brand rewrite, circuit breaker, `__t=` handoff JS in proxy stub pages.
- Delete `apps/backend/tests/test_paperclip_proxy.py`.
- Delete the `X-Isol8-Public-Host` parameter mapping in `api-stack.ts` (CDK).
- Retire `*.company.isol8.co` DNS record + ACM cert.
- Remove the host-conditional dispatch middleware in `apps/backend/main.py` (T16 hook).

## 9. Error handling

- **Per-user Better Auth session expired (401):** BFF invalidates cached session, signs in again, retries once. Two-401-in-a-row → return 401 to client (assume password rotation needed; rare; manual ops).
- **Admin session expired (401):** existing `invalidate_admin_session()` + retry, already in `paperclip_admin_session.py`.
- **Paperclip 5xx:** 503 to client. No automatic retry inside a single request. Add a per-route success-rate metric for upstream availability monitoring.
- **Org membership race:** member added to Clerk org → webhook fires → user opens `/teams` before admin-approve completes → BFF returns 202 with `{ status: "provisioning" }`; client polls. Same shape as the existing OpenClaw container-provisioning UX.
- **Container not yet provisioned but Paperclip company exists** (rare; failed container provisioning): BFF returns 503 with `{ status: "container_offline" }`; UI surfaces "your team workspace is set up but your container is offline — restart from `/chat`."
- **Adapter URL allowlist mismatch:** synthesize_openclaw_adapter raises a 500. This is an operator bug, not user input — the URL is read from our own `containers` table. Add an alarm on this metric.

## 10. Testing

- **Backend unit:** mock Paperclip admin and user session clients via `httpx_mock`. Verify adapter-config synthesis rejects every form of client-supplied `adapterType` / `adapterConfig` / nested URL fields. Verify per-user session sign-in retry-on-401.
- **Backend integration:** moto + a mock Paperclip via `httpx_mock`. End-to-end: create user → provision (Case A and Case B) → create agent → wake → see run.
- **Frontend unit:** SWR mocks for each panel. Render-with-loading-states tests.
- **Frontend E2E (Playwright):** existing journey tests in `apps/frontend` + add a `/teams` flow on `e2e-dev.yml`. Use the existing `isol8-e2e-testing@mailsac.com` account. Smoke: create-agent → wake → run completes → row in inbox.
- **Migration test:** verify legacy `dev.company.isol8.co` paths 301 correctly during Phase 2.

## 11. Out of scope

- Org chart visualization
- Skills upload / OpenClaw↔Paperclip skill sync
- Multi-environment workflows
- Paperclip secrets store
- Paperclip LLM provider config
- Multi-member invite UI inside `/teams` (Clerk-owned)
- Operator/admin surfaces for instance-level Paperclip ops (separate `/admin/paperclip` iframe behind admin-host gate, future)
- V2 short-TTL caching of per-user Better Auth sessions
- Native rebuild of any Tier 4 panel; if any becomes operationally needed, surface as iframe under `admin.isol8.co/paperclip` rather than at `/teams`
