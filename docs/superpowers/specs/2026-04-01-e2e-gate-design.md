# E2E Gate: Replace Manual Approval with Playwright Tests

**Issue:** [Isol8AI/isol8#32](https://github.com/Isol8AI/isol8/issues/32)
**Date:** 2026-04-01
**Status:** Approved

## Overview

Replace the `trstringer/manual-approval` gate in the CDK pipeline with an automated Playwright e2e suite that exercises the full user journey against the live dev environment (`https://dev.isol8.co`). Prod only deploys if all tests pass.

## Goals

- Every merge to `main` triggers the full e2e suite before prod deploys
- Tests cover: auth → subscribe → provision → chat → unsubscribe → deprovision
- Failures block prod and surface debug artifacts (screenshots, traces, HTML report)
- Tests are idempotent — safe to re-run after a mid-run failure

## Non-Goals

- Separate nightly test job (one comprehensive suite per commit only)
- Cross-browser testing (Chromium only — most reliable with Clerk Testing Tokens)
- Testing Clerk sign-in UI (bypassed via Testing Tokens)
- Testing Stripe's hosted Checkout UI (subscription created via Stripe API — see below)

---

## Pipeline Change

**File:** `apps/infra/lib/app.ts`

Replace the `approvalStep` block (manual approval via `trstringer/manual-approval@v1`) with `e2eGate`. The `ApproveProduction` block and its `issues: WRITE` permission are deleted entirely.

```typescript
const e2eGate = new GitHubActionStep("E2EGate", {
  jobSteps: [
    { name: "Checkout", uses: "actions/checkout@v4" },
    { name: "Setup pnpm", uses: "pnpm/action-setup@v4" },
    {
      name: "Setup Node.js",
      uses: "actions/setup-node@v4",
      with: { "node-version": "20", cache: "pnpm" },
    },
    {
      name: "Install dependencies",
      // Run from repo root to respect workspace pnpm-lock.yaml
      run: "pnpm install --frozen-lockfile",
    },
    {
      name: "Install Playwright browsers",
      run: "cd apps/frontend && npx playwright install chromium --with-deps",
    },
    {
      name: "Run E2E gate tests",
      run: "cd apps/frontend && npx playwright test --project=chromium",
      env: {
        BASE_URL: "https://dev.isol8.co",
        NEXT_PUBLIC_API_URL: "${{ secrets.NEXT_PUBLIC_API_URL_DEV }}",
        CLERK_PUBLISHABLE_KEY: "${{ secrets.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY_DEV }}",
        CLERK_SECRET_KEY: "${{ secrets.CLERK_SECRET_KEY }}",
        // CLERK_SECRET_KEY must be the DEV Clerk instance key (same instance as dev.isol8.co)
        // Confirm isol8-e2e-testing@mailsac.com exists in this Clerk dev instance
        STRIPE_SECRET_KEY: "${{ secrets.STRIPE_SECRET_KEY }}",
        // STRIPE_SECRET_KEY must be a test mode key (sk_test_...) — never a live key
        // Dev Starter price ID is hardcoded in service-stack.ts (price_1TF5MDI54BysGS3rlT80MMI8) — no secret needed
        E2E_CLERK_USER_USERNAME: "${{ secrets.E2E_CLERK_USER_USERNAME }}",
        E2E_CLERK_USER_PASSWORD: "${{ secrets.E2E_CLERK_USER_PASSWORD }}",
        // Required by @clerk/testing/playwright's clerk.signIn()
      },
    },
    {
      name: "Upload Playwright report",
      uses: "actions/upload-artifact@v4",
      if: "always()",
      with: {
        name: "playwright-report",
        path: "apps/frontend/playwright-report/",
        "retention-days": "7",
      },
    },
  ],
});
```

Swap `pre: [approvalStep]` → `pre: [e2eGate]` on the prod stage.

**Important:** After editing `app.ts`, run `cdk synth` from `apps/infra` and commit the regenerated `.github/workflows/deploy.yml`. Without this step the pipeline change has no effect — `deploy.yml` is the file GitHub Actions actually reads.

---

## Test Structure

```
apps/frontend/tests/e2e/
  global.setup.ts          ← existing, unchanged (clerkSetup())
  landing.spec.ts          ← existing, unchanged
  journey.spec.ts          ← NEW — full e2e suite (serial, retries: 0)
  helpers/
    stripe.ts              ← NEW — Stripe API helpers
    provision.ts           ← NEW — provision/deprovision helpers
```

### `journey.spec.ts` — Full User Journey (Serial)

```typescript
test.describe.configure({ mode: 'serial' });
test.use({ retries: 0 }); // Destructive side effects — no retries
```

Steps in order:

| Step | Description | Timeout |
|------|-------------|---------|
| 1. Idempotent cleanup | Cancel existing subscription (any state) if any; deprovision container if running | 2 min |
| 2. Auth | Clerk Testing Token via `clerk.signIn()` → navigate to `/chat`, verify authenticated | 30 sec |
| 3. Subscribe | Create Stripe subscription via API with `pm_card_visa` → poll `GET /api/v1/billing/account` until `is_subscribed === true` | 1 min |
| 4. Provision | POST `/api/v1/debug/provision` → poll container status → wait for `status === "running"` | **5 min** |
| 5. Chat | Select agent → send message → verify streaming chunks → verify `done` event | 2 min |
| 6. Cleanup (afterAll) | Cancel subscription via Stripe API → deprovision container | 2 min |

**Overall suite timeout:** `globalTimeout: 15 * 60 * 1000` in `playwright.config.ts`. Note: `workers: 1` means `landing.spec.ts` runs before `journey.spec.ts` serially. The `landing.spec.ts` tests are fast (~30 sec) and use `retries: 2` at the global level. The 15-minute `globalTimeout` covers the full suite including landing tests. If landing tests exhaust retries (worst case ~90 sec), the journey spec still has ~13 min — sufficient for the 5-min provision timeout plus all other steps.

Cleanup (step 6) runs in `test.afterAll`. Since `retries: 0` is set, `afterAll` fires immediately after any test failure — no retry gap.

### Stripe subscription approach (step 3)

Stripe's hosted Checkout page uses iframe card fields, dynamic selectors, and bot detection — unreliable for Playwright automation. Use the Stripe Node SDK directly in the test helper:

1. Look up or create the Stripe customer for `isol8-e2e-testing@mailsac.com`
2. Attach `pm_card_visa` (Stripe's built-in test payment method) to the customer
3. Create a subscription using the dev Starter price ID `price_1TF5MDI54BysGS3rlT80MMI8` (hardcoded in `apps/infra/lib/stacks/service-stack.ts`)
4. After `createSubscription()` returns, poll `GET /api/v1/billing/account` until `is_subscribed === true` — required because Stripe fires a webhook asynchronously, and the backend updates `plan_tier` only after receiving `customer.subscription.created`. Poll with ~5s interval, 60s max timeout.

This tests that the subscription state flows correctly through the app (webhook → backend → database → UI) without depending on Stripe's hosted UI.

### Container status (step 4)

Poll `GET /api/v1/container/status` (authenticated). The fully-ready terminal state is:

```
status === "running"    (or substatus === "gateway_healthy")
```

Failure state (stop polling, fail test): `status === "error"`.
Intermediate states (continue polling): `status === "provisioning"`.

### `helpers/stripe.ts`

- `cancelSubscriptionIfExists(email)` — lists customers by email (handles multiple matches); for each customer, cancels any subscription with status `active`, `trialing`, or `incomplete`. Safe to call when no subscription exists.
- `createSubscription(email, priceId)` — looks up or creates Stripe customer for email, attaches `pm_card_visa`, creates subscription with `default_payment_method` set.
- `waitForSubscriptionActive(apiUrl, authToken, timeoutMs)` — polls `GET /api/v1/billing/account` until `is_subscribed === true` or timeout. Bridges the async webhook delivery gap.

### `helpers/provision.ts`

- `deprovisionIfExists(apiUrl, authToken)` — calls `DELETE /api/v1/debug/provision`. Treats 404 and 503 as "not running" — swallows both without throwing. Only throws on unexpected errors.
- `waitForRunning(apiUrl, authToken, timeoutMs)` — polls `GET /api/v1/container/status` until `status === "running"` or timeout. Throws on `status === "error"`.

---

## Playwright Config Changes

**File:** `apps/frontend/playwright.config.ts`

Three changes:

1. `baseURL` reads from env:
   ```typescript
   baseURL: process.env.BASE_URL || 'http://localhost:3000',
   ```

2. `globalTimeout` added:
   ```typescript
   globalTimeout: 15 * 60 * 1000, // 15 minutes — covers full suite including landing tests
   ```

3. `webServer` — suppress when `BASE_URL` is set. Remove the broken backend entry (the path `../backend/env/bin/uvicorn` is a local virtualenv path that does not exist in CI). Frontend-only for local dev:
   ```typescript
   webServer: !process.env.BASE_URL
     ? [{
         command: 'pnpm run dev',
         // cwd defaults to apps/frontend/ (the config file's directory) — correct
         url: 'http://localhost:3000',
         reuseExistingServer: !process.env.CI,
         timeout: 120000,
       }]
     : undefined,
   ```
   For local e2e runs against localhost: start the backend manually (`uv run uvicorn main:app --port 8000`) before running Playwright.

---

## Dependencies

**Add to `apps/frontend/package.json` (devDependencies):**

```json
"stripe": "^17.x"
```

**After adding, run `pnpm install` from the repo root and commit the updated `pnpm-lock.yaml` in the same PR.** Without this, `pnpm install --frozen-lockfile` in the CI gate step will fail with a lockfile mismatch.

---

## Secrets

### New secrets to add to GitHub Actions

| Secret | Value | Notes |
|--------|-------|-------|
| `E2E_CLERK_USER_USERNAME` | `isol8-e2e-testing@mailsac.com` | Required by `clerk.signIn()` |
| `E2E_CLERK_USER_PASSWORD` | _(test account password)_ | Required by `clerk.signIn()` |

### Already present (no action needed)

| Secret | Used for | Constraint |
|--------|----------|------------|
| `CLERK_SECRET_KEY` | Clerk Testing Tokens (`clerkSetup()`) | Must be dev Clerk instance key — same instance as `dev.isol8.co` |
| `STRIPE_SECRET_KEY` | Stripe API (subscription create/cancel) | Must be `sk_test_...` — never a live key |
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY_DEV` | Frontend auth | Already used in `DeployVercelDev` |
| `NEXT_PUBLIC_API_URL_DEV` | Backend API URL | Already used in `DeployVercelDev` |

### Test account

- **Email:** `isol8-e2e-testing@mailsac.com`
- **Mailbox:** Mailsac (for email verification if needed)
- **MFA:** disabled
- **Instance:** Clerk dev instance (same as `dev.isol8.co`)
- Created: 2026-04-01

---

## Error Handling & Observability

- **Screenshots on failure** — Playwright captures screenshot at point of failure (already configured)
- **Traces on first retry** — moot for `journey.spec.ts` (retries: 0), still applies to `landing.spec.ts`
- **HTML report upload** — `actions/upload-artifact@v4` with `if: always()` — captures artifacts for partial failures and flaky runs, not just hard failures
- **Per-step timeouts** — enforced via `test.step('name', async () => {...}, { timeout: ms })` within each test
- **`test.afterAll` cleanup** — fires immediately after failure (retries: 0 on journey spec), ensures clean state for next run
- **Global timeout** — `globalTimeout: 15 * 60 * 1000` prevents runaway GitHub Actions jobs

---

## Files Changed

| File | Change |
|------|--------|
| `apps/infra/lib/app.ts` | Replace `approvalStep` with `e2eGate`; delete `ApproveProduction` and `issues: WRITE` permission |
| `.github/workflows/deploy.yml` | Regenerated via `cdk synth` — commit the output |
| `apps/frontend/playwright.config.ts` | `baseURL` from env; `globalTimeout`; conditional `webServer` (frontend only, `cwd` defaults to `apps/frontend/`) |
| `apps/frontend/package.json` | Add `stripe` devDependency |
| `pnpm-lock.yaml` | Updated after `pnpm install` from repo root |
| `apps/frontend/tests/e2e/journey.spec.ts` | New — full e2e suite |
| `apps/frontend/tests/e2e/helpers/stripe.ts` | New — Stripe API helpers |
| `apps/frontend/tests/e2e/helpers/provision.ts` | New — provision/deprovision helpers |
| `apps/frontend/src/components/chat/MessageList.tsx` | Add `data-role={msg.role}` to message wrapper div for e2e selector |

---

## Out of Scope

- Nightly job (dropped in favour of single comprehensive gate)
- Firefox / WebKit browser coverage
- Testing Clerk sign-in UI
- Testing Stripe's hosted Checkout browser UI
- Staging / prod e2e tests
