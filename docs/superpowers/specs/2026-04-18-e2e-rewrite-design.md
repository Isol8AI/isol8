# E2E Test Rewrite — Design

**Status:** approved design, awaiting plan

**Goal:** replace the current shared-state, admin-API-heavy E2E gate with per-run isolated UI-driven tests that actually exercise user flows and catch regressions in the code paths users hit.

---

## Motivation

Tonight's incidents made the problems with the current E2E concrete:

- **Journey gate signed in as the wrong user** for 18 hours because Clerk's `?email_address[]=X` filter is unreliable and we used `users[0]` blindly — every deploy ran subscribe→cancel→re-subscribe against a manually-testing account (`prasiddha@gmail.com`) instead of `isol8-e2e-testing@mailsac.com`. Fixed in PR #300 but the structural fragility remains.
- **`useGateway` regression (PR #302 fix)** — a Clerk-user deps change in PR #279 (the desktop app PR) caused WebSocket teardown on every user resolve, silently killing `agents.list`. E2E didn't catch it because the current test only asserts "chat round-trip works" on a steady-state user, not "agent appears quickly on a fresh mount."
- **Chat Smoke deadlock** — smoke's `is_subscribed` precheck depends on Journey leaving a live sub; when Journey targets the wrong user, smoke fails indefinitely, PRs can't merge without admin override.
- **Stripe Checkout UI is never exercised** — `helpers/stripe.ts:ensureBillingCustomer` POSTs `/billing/checkout` and *discards* the returned URL, then uses `stripe.subscriptions.create()` via admin API. Bugs in the Subscribe button → `/billing/checkout` → Stripe Checkout → `checkout.session.completed` → backend webhook → `/chat?subscription=success` redirect path silently slip through.
- **Org onboarding path is 100% untested** — the class of bug `ChatLayout.tsx:111-117` explicitly calls out ("The 3 orphan billing rows we see in prod today came from exactly this race") has zero coverage.
- **Gate has been disabled to unblock prod** (PR #222, 10 days ago). When a gate fails wrong, humans bypass it — signal that the current gate is not a viable permanent blocker.
- **Sign-in approach has churned through 4 implementations** (UI form → iframe frameLocator → mailsac OTP → sign-in tickets) and needed another fix yesterday. Structurally unstable.

## What we're building

Two Playwright describe blocks, each a `serial`-mode flow with a **per-run fresh Clerk user** and **hard-fail teardown**. Runs in the post-deploy `E2EGate` step only. No PR-time E2E.

### Flows

**Flow A — Personal happy path** (single per-run user, ordered tests)
1. `beforeAll`: Clerk admin-create user with email + password + `unsafe_metadata.e2e_run_id`
2. Test — Sign in via `/sign-in` form: fill email + password, submit, verify redirect to `/onboarding`
3. Test — Click "Personal" on `/onboarding`, verify redirect to `/chat`
4. Test — Free-tier chat: provision auto-fires, wait for container healthy, send message, assert assistant response arrives
5. Test — Upgrade to Starter via `/settings/billing`: click Upgrade → follow redirect to `checkout.stripe.com` → fill test card `4242 4242 4242 4242` → submit → land on `/chat?subscription=success` → verify `is_subscribed=true`
6. Test — Starter-tier chat: send message, assert response, verify model flipped to `qwen.qwen3-vl-235b-a22b` via `sessions.list` token-usage read
7. `afterAll`: Stripe teardown → backend teardown (`DELETE /debug/user-data`) → Clerk teardown → **verification pass, fail run if anything leaks**

**Flow B — Org happy path** (separate per-run user, parallel with Flow A)
Identical to Flow A except Test 2 takes the Organization path: click "Organization" → fill Clerk `CreateOrganization` widget → verify org activates → verify redirect to `/chat` with org context. The remaining tests exercise the backend's `resolve_owner_id(auth)` org path (DDB rows keyed by `org_id`, not `user_id`).

### Lifecycle

**Per-run identity** (stable across the flow's tests):
```ts
const rand = crypto.randomBytes(6).toString("hex");
const runId = `${Date.now()}-${rand}`;
const email = `isol8-e2e-${rand}@mailsac.com`;
const password = crypto.randomBytes(24).toString("base64url");
// clerkUserId returned by admin-create; primary identifier afterward
```

**Setup** (`beforeAll`, per flow):
1. `POST https://api.clerk.com/v1/users` with `email_address[0]=email`, `password`, `unsafe_metadata.e2e_run_id=runId`, `unsafe_metadata.onboarded=false`. Returns `clerkUserId`.
2. Warm browser context with `x-vercel-protection-bypass` header, navigate to `/sign-in`.

**Tests** drive the UI only. No admin-API calls except inside the `beforeAll` / `afterAll` lifecycle hooks. An `E2EUser` fixture (see Fixture Architecture) exposes authenticated `fetch` access for assertion-only queries.

**Teardown** (`afterAll`, idempotent, runs even on test failure):
1. Stripe: `stripe.customers.list({email})` → cancel each sub → `stripe.customers.delete(customerId)`
2. Backend: `DELETE /api/v1/debug/user-data` (new endpoint, see Backend Changes) — one call tears down ECS service, EFS access point, per-user EFS folder, all per-user DDB rows, Cloud Map registration
3. Clerk: if an org was created, `DELETE /v1/organizations/{orgId}`; then `DELETE /v1/users/{clerkUserId}`
4. **Verification pass** — in parallel, all must succeed or the run fails red:
   - `stripe.customers.list({email, limit: 1})` → empty
   - `GET https://api.clerk.com/v1/users?email_address[]=<email>` + in-JS filter → no match
   - `GET /api/v1/debug/ddb-rows?owner_id=<clerkUserId>` → `{users: 0, containers: 0, billing-accounts: 0, ...}` across all 8 tables
   - `GET /api/v1/debug/efs-exists?path=/mnt/efs/users/<clerkUserId>` → `{exists: false}`
   - ECS service gone (`describe_services` → MISSING)

Cleanup step failures are tolerated (the step catches "not found" as success — cleanup is idempotent). The **verification pass** is the red line: if anything has leaked after cleanup, the test run fails.

## Architecture

### Fixture design

Playwright fixture with `scope: "worker"` — each flow gets its own user, created once, torn down once:

```ts
// tests/e2e/fixtures/user.ts
export const test = base.extend<{}, { e2eUser: E2EUser }>({
  e2eUser: [async ({}, use) => {
    const ctx = await createUser({ role: "personal" | "org" });
    try {
      await use(ctx);
    } finally {
      await cleanupUser(ctx);
    }
  }, { scope: "worker" }],
});
```

### `E2EUser` shape

```ts
type E2EUser = {
  runId: string;          // Date-hex, correlation key across Stripe/Clerk/backend
  email: string;
  password: string;
  clerkUserId: string;
  customerId?: string;    // populated by Subscribe step
  orgId?: string;         // Org flow only
  
  api: AuthedFetch;       // api.get("/billing/account") with auto-refreshed JWT
  stripe: StripeAdminClient;
  ddb: DDBReader;         // scoped to this owner_id
};
```

`AuthedFetch` reads token fresh via `page.evaluate(() => Clerk.session.getToken())` on every call — no ambient token state.

### Stripe Checkout driver

```ts
await drivers.completeStripeCheckout(page, {
  cardNumber: "4242 4242 4242 4242",
  cardExpiry: "12 / 34",
  cardCvc: "123",
});
```

Waits for redirect to `checkout.stripe.com/**`, fills card fields using Stripe's stable `autocomplete=cc-*` selectors, clicks Subscribe, waits for redirect back to `**/chat?subscription=success`. No iframes in test-mode Stripe Checkout.

### Assertion helpers

```ts
await assertions.billingTier(user, "starter");        // polls GET /billing/account
await assertions.containerHealthy(user, { timeout: 10 * 60_000 });
await assertions.chatResponded(page, { timeout: 90_000 });
await assertions.modelUsed(user, "qwen.qwen3-vl-235b-a22b");
```

Centralized so tests read like behavior specs.

### Run ID propagation (observability)

`runId` propagates through:
- **Clerk** — `unsafe_metadata.e2e_run_id` on the user
- **Stripe** — `metadata.e2e_run_id` set on the customer (via admin API after customer is created by `/billing/checkout`)
- **Backend logs** — every test-issued HTTP request carries `X-E2E-Run-Id: <runId>` header. FastAPI middleware binds it to structured log context so every log line for that request includes `e2e_run_id` field
- **CloudWatch** — filter `{ $.e2e_run_id = "<runId>" }` returns every log line the backend emitted for that test run

When an E2E fails, the Playwright report logs the `runId`; ops filters CloudWatch by that ID and sees exactly what backend did.

### Environment configuration

- New `apps/frontend/tests/e2e/.env.example` documenting every required var
- `STRIPE_STARTER_PRICE_ID` pulled from env (today it's hardcoded at `journey.spec.ts:8` — rot risk when prices change)
- Required vars: `BASE_URL`, `NEXT_PUBLIC_API_URL`, `CLERK_SECRET_KEY`, `STRIPE_SECRET_KEY`, `STRIPE_STARTER_PRICE_ID`, `VERCEL_AUTOMATION_BYPASS_SECRET`

## Backend changes

### New endpoints (`routers/debug.py`, gated `settings.ENVIRONMENT != "prod"`)

| Endpoint | Purpose |
|---|---|
| `DELETE /api/v1/debug/user-data` | Atomic full teardown for the authenticated owner. Stops + deletes ECS service, deletes per-user EFS access point, **`rm -rf /mnt/efs/users/{owner_id}/`** (new — today's `/debug/provision` doesn't do this), deregisters all per-user task-def revisions, deletes rows from 8 per-user DDB tables (users, containers, billing-accounts, api-keys, usage-counters, pending-updates, channel-links, ws-connections). Returns `{deleted: {ecs, efs, ddb: [tables]}}`. Auth: caller's own JWT only (can only delete own data). |
| `GET /api/v1/debug/efs-exists?path=...` | Read-only. Path must start with `/mnt/efs/users/` (validated server-side). Returns `{exists: bool}`. |
| `GET /api/v1/debug/ddb-rows?owner_id=...` | Read-only. Returns `{tables: {users: 0, containers: 0, ...}}` — row counts per table for owner. |

### New middleware

`apps/backend/core/observability/e2e_correlation.py` — reads `X-E2E-Run-Id` header, binds to structured log context. ~15 LOC. Plugged into `main.py` FastAPI middleware stack.

### No existing endpoint changes

`/billing/checkout`, `/container/provision`, `/container/status`, `/users/sync`, `/billing/portal` stay as-is. E2E drives them through the real UI.

## CI wiring

### Replace `E2EGate` in `apps/infra/lib/app.ts`

```ts
const e2eGate = new GitHubActionStep("E2EGate", {
  jobSteps: [
    // Checkout, setup node, install deps, install Playwright browsers (unchanged)
    {
      name: "Run E2E gate tests",
      run: "cd apps/frontend && npx playwright test --workers=2",
      env: {
        BASE_URL: "https://dev.isol8.co",
        NEXT_PUBLIC_API_URL: "${{ secrets.NEXT_PUBLIC_API_URL_DEV }}",
        NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY: "${{ secrets.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY_DEV }}",
        CLERK_SECRET_KEY: "${{ secrets.CLERK_SECRET_KEY_DEV }}",
        STRIPE_SECRET_KEY: "${{ secrets.STRIPE_SECRET_KEY }}",
        STRIPE_STARTER_PRICE_ID: "${{ secrets.STRIPE_STARTER_PRICE_ID_DEV }}",
        VERCEL_AUTOMATION_BYPASS_SECRET: "${{ secrets.VERCEL_AUTOMATION_BYPASS_SECRET }}",
      },
    },
    // Upload playwright-report artifact on failure (unchanged)
  ],
});
```

Key changes:
- `--grep-invert='Chat Smoke'` removed (Chat Smoke is gone)
- `--workers=2` enables Personal + Org flows to parallelize
- New env: `STRIPE_STARTER_PRICE_ID_DEV`

### Remove

- `apps/frontend/tests/e2e/journey.spec.ts` (deleted)
- `apps/frontend/tests/e2e/chat.smoke.spec.ts` (deleted)
- `apps/frontend/tests/e2e/helpers/stripe.ts::createSubscription` (admin-API bypass, deleted)
- `.github/workflows/frontend-ci.yml` chat-smoke job (deleted; lint+build+vitest remain)
- `apps/frontend/tests/e2e/helpers/provision.ts::deprovisionIfExists` (dead code once new teardown ships)

### Keep

- `apps/frontend/tests/e2e/landing.spec.ts` as-is
- `apps/frontend/tests/e2e/helpers/stripe.ts::cancelSubscriptionIfExists` + customer delete (admin API is correct for teardown)
- Vitest unit tests for helpers (expand to cover new `createUser` / `cleanupUser` / Stripe driver)

### New GitHub secrets

- `STRIPE_STARTER_PRICE_ID_DEV`

### Cutover

Hard cutover. Old Journey + Chat Smoke deleted in the same PR that adds the new gate. First deploy after merge runs the new gate against dev; if it fails, we fix forward or revert the PR.

## Unit tests

Expand `tests/unit/e2e-helpers/` to cover:
- `createUser` — mock Clerk admin API, verify correct payload
- `cleanupUser` — mock all three systems, verify idempotency + hard-fail on verification
- `drivers/stripe-checkout.ts` — no live browser, but mock the page interface and verify selector resilience logic
- `assertions/*` — mock fetch/page, verify polling + error messages

## Out of scope

Explicitly deferred so the MVP stays shipped-able:

- **Sweeper job** for drift cleanup — not needed if hard-fail teardown works. Add if accumulation becomes a problem in practice.
- **PR-time e2e** of any kind.
- **Upgrade Starter → Pro** (single upgrade free→Starter is enough for MVP).
- **Re-subscribe after cancel** (PR #297 409 guard) — satisfying but out.
- **Free-tier scale-to-zero verification** (too slow — 5 min idle).
- **Stripe webhook failure recovery** (assume webhooks fire).
- **Org invitation flow** (inviting a second user, member sign-in).
- **Channel setup** (keep the dismiss-wizard helper, don't drive OAuth).
- **Desktop app e2e** (Tauri).
- **Multi-org in same user** (invariant is one org per user).
- **Error-state UI** (container error, payment failed) — happy path only.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| ECS cold-start is ~10 min; two parallel flows at ~15 min each may exceed the pipeline's global timeout | Playwright global timeout set to 20 min; the deploy pipeline already budgets for 18 min Journey today so ~20 min is within range |
| Stripe Checkout UI flake (test-mode is stable but not zero-flake) | Retry Subscribe step once on redirect timeout; if it fails twice, fail the run |
| Clerk admin-create user occasionally 500s | Retry once at fixture setup; if it fails twice, fail fast with clear error |
| EFS `rm -rf` on backend task could hit permission issues (UID 1000 vs root) | Backend task runs as root; inline delete via `shutil.rmtree` works. Verified today during the manual clean-slate reset |
| Verification pass asserts "nothing leaked" but races a slow-draining DDB write | Run verification with a 30-second settling wait after deletions; each verification check is itself idempotent and can retry once |
| `/debug/user-data` is a destructive endpoint; if `settings.ENVIRONMENT != "prod"` gate regresses, could wipe prod | Additional guard: endpoint accepts only the caller's own `owner_id` (no arbitrary IDs), refuses if caller's email doesn't match an e2e pattern. Single human-operator safety net on top of the env gate |

## Success criteria

- Post-deploy E2EGate runs in ≤20 min wallclock
- Passes on 10 consecutive deploys without flake-retries
- Catches a deliberately-introduced regression in each of: Subscribe button routing, Stripe webhook → billing row flip, container provision, chat round-trip, onboarding redirect
- Zero Stripe customers / Clerk users / DDB rows / EFS folders accumulate over 30 days of runs
- Contributors can run full E2E locally against dev with only the documented `.env.example` vars set
