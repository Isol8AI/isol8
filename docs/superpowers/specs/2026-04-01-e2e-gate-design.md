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

- Separate nightly test job (dropped in favour of one comprehensive suite per commit)
- Cross-browser testing (Chromium only — most reliable with Clerk Testing Tokens)
- Testing Clerk sign-in UI (bypassed via Testing Tokens)

---

## Pipeline Change

**File:** `apps/infra/lib/app.ts`

Replace `approvalStep` (manual approval via `trstringer/manual-approval@v1`) with `e2eGate` (`GitHubActionStep`). The `ApproveProduction` block and its `issues: WRITE` permission are deleted entirely.

```typescript
const e2eGate = new GitHubActionStep("E2EGate", {
  jobSteps: [
    { name: "Checkout", uses: "actions/checkout@v4" },
    { name: "Setup pnpm", uses: "pnpm/action-setup@v4" },
    { name: "Setup Node.js", uses: "actions/setup-node@v4", with: { "node-version": "20", cache: "pnpm" } },
    { name: "Install dependencies", run: "cd apps/frontend && pnpm install" },
    { name: "Install Playwright browsers", run: "cd apps/frontend && npx playwright install chromium --with-deps" },
    {
      name: "Run E2E gate tests",
      run: "cd apps/frontend && npx playwright test --project=chromium",
      env: {
        BASE_URL: "https://dev.isol8.co",
        NEXT_PUBLIC_API_URL: "${{ secrets.NEXT_PUBLIC_API_URL_DEV }}",
        CLERK_PUBLISHABLE_KEY: "${{ secrets.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY_DEV }}",
        CLERK_SECRET_KEY: "${{ secrets.CLERK_SECRET_KEY }}",
        STRIPE_SECRET_KEY: "${{ secrets.STRIPE_SECRET_KEY }}",
        E2E_CLERK_USER_USERNAME: "${{ secrets.E2E_CLERK_USER_USERNAME }}",
        E2E_CLERK_USER_PASSWORD: "${{ secrets.E2E_CLERK_USER_PASSWORD }}",
      },
    },
    {
      name: "Upload Playwright report",
      uses: "actions/upload-artifact@v4",
      if: "failure()",
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

---

## Test Structure

```
apps/frontend/tests/e2e/
  global.setup.ts          ← existing, unchanged (clerkSetup())
  landing.spec.ts          ← existing, unchanged
  journey.spec.ts          ← NEW — full e2e suite (serial)
  helpers/
    stripe.ts              ← NEW — Stripe API helpers
    provision.ts           ← NEW — provision/deprovision helpers
```

### `journey.spec.ts` — Full User Journey (Serial)

Runs as `test.describe.configure({ mode: 'serial' })`. Steps in order:

| Step | Description | Timeout |
|------|-------------|---------|
| 1. Idempotent cleanup | Cancel existing subscription if any; deprovision container if running | 2 min |
| 2. Auth | Clerk Testing Token → navigate to `/chat`, verify authenticated | 30 sec |
| 3. Subscribe | Navigate to billing → Stripe Checkout → enter `4242 4242 4242 4242` → verify redirect back | 2 min |
| 4. Provision | POST `/api/v1/debug/provision` → poll container status → wait for "connected" | **5 min** |
| 5. Chat | Select agent → send message → verify streaming chunks → verify `done` event | 2 min |
| 6. Cleanup | Cancel subscription via Stripe API → deprovision container | 2 min |

**Overall suite timeout:** 15 min

Cleanup (step 6) runs in `test.afterAll` so it executes even if earlier steps fail, ensuring the next run starts with clean state.

### `helpers/stripe.ts`

- `cancelSubscriptionIfExists(email)` — uses Stripe API to find and cancel any active subscription for the test account
- `getSubscriptionStatus(email)` — returns current subscription state

### `helpers/provision.ts`

- `deprovisionIfExists(authToken)` — calls `DELETE /api/v1/debug/provision` if container exists
- `waitForConnected(authToken, timeoutMs)` — polls container status until "connected" or timeout

---

## Playwright Config Changes

**File:** `apps/frontend/playwright.config.ts`

Two changes only:

1. `baseURL` reads from env:
   ```typescript
   baseURL: process.env.BASE_URL || 'http://localhost:3000',
   ```

2. `webServer` only starts local servers when `BASE_URL` is not set:
   ```typescript
   webServer: (process.env.CI && !process.env.BASE_URL) ? [...existing...] : undefined,
   ```

---

## Secrets

### New secrets to add to GitHub Actions

| Secret | Value |
|--------|-------|
| `E2E_CLERK_USER_USERNAME` | `isol8-e2e-testing@mailsac.com` |
| `E2E_CLERK_USER_PASSWORD` | _(test account password)_ |

### Already present (no action needed)

| Secret | Used for |
|--------|----------|
| `CLERK_SECRET_KEY` | Clerk Testing Tokens |
| `STRIPE_SECRET_KEY` | Stripe API cleanup |
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY_DEV` | Frontend auth |
| `NEXT_PUBLIC_API_URL_DEV` | Backend API URL |

### Test account

- **Email:** `isol8-e2e-testing@mailsac.com`
- **Mailbox:** Mailsac (public, for email verification if needed)
- **MFA:** disabled
- Created: 2026-04-01

---

## Error Handling & Observability

- **Screenshots on failure** — Playwright captures screenshot at point of failure (already configured)
- **Traces on first retry** — full Playwright trace for replay (already configured)
- **HTML report upload** — on failure, `actions/upload-artifact@v4` uploads `playwright-report/` to GitHub Actions (7-day retention). Accessible directly from the failed workflow run.
- **Per-step timeouts** — each test step has its own timeout (see table above) so a hang doesn't silently consume the full 15 min budget
- **`test.afterAll` cleanup** — runs regardless of pass/fail, ensures idempotent state for next run

---

## Files Changed

| File | Change |
|------|--------|
| `apps/infra/lib/app.ts` | Replace `approvalStep` with `e2eGate` |
| `apps/frontend/playwright.config.ts` | `baseURL` from env; conditional `webServer` |
| `apps/frontend/tests/e2e/journey.spec.ts` | New — full e2e suite |
| `apps/frontend/tests/e2e/helpers/stripe.ts` | New — Stripe API helpers |
| `apps/frontend/tests/e2e/helpers/provision.ts` | New — provision helpers |

---

## Out of Scope

- Nightly job (dropped)
- Firefox / WebKit browser coverage
- Testing Clerk sign-in UI
- Staging / prod e2e tests
