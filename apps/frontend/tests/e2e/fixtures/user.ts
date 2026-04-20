/**
 * E2E user lifecycle helper.
 *
 * Tests call `createE2EUser(page, role)` in beforeAll, drive the UI flow, then
 * call `cleanupUser(user)` in afterAll. Cleanup orchestrates Stripe -> backend
 * -> Clerk in that order, then re-queries Stripe + Clerk to hard-fail if
 * anything was left behind. This keeps the dev environment clean across runs.
 *
 * NOTE: the bare `e2eUser` Playwright fixture below is intentionally a trap
 * (it always throws). The pattern is for specs to call `createE2EUser`
 * directly inside `beforeAll`, not via a fixture — role and orgId need to be
 * decided per-spec, and Playwright's worker fixtures don't compose cleanly
 * with that. Tasks 11/12 (the spec files) will use the explicit helpers.
 */

import { test as base, type Page } from '@playwright/test';
import crypto from 'crypto';
import { createUser, deleteUser, deleteOrg, findUserByEmail } from './clerk-admin';
import { cancelSubsAndDeleteCustomer, findCustomerByEmail } from './stripe-admin';
import { AuthedFetch, AuthedFetchError } from './api';
import { DDBReader } from './ddb-reader';

export type E2EUserRole = 'personal' | 'org';

export type E2EUser = {
  runId: string;
  email: string;
  password: string;
  clerkUserId: string;
  orgId?: string;
  page: Page;
  api: AuthedFetch;
  ddb: DDBReader;
};

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000/api/v1';

function makeRunId(): string {
  return `${Date.now()}-${crypto.randomBytes(3).toString('hex')}`;
}

export async function createE2EUser(
  page: Page,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  _role: E2EUserRole,
): Promise<E2EUser> {
  const secretKey = process.env.CLERK_SECRET_KEY;
  if (!secretKey) {
    throw new Error('CLERK_SECRET_KEY required for createE2EUser');
  }

  const runId = makeRunId();
  const rand = crypto.randomBytes(6).toString('hex');
  const email = `isol8-e2e-${rand}@mailsac.com`;
  const password = crypto.randomBytes(24).toString('base64url');

  const clerkUserId = await createUser({ secretKey, email, password, runId });
  const api = new AuthedFetch(page, API_URL, runId);
  const ddb = new DDBReader(api, clerkUserId);

  return { runId, email, password, clerkUserId, page, api, ddb };
}

export async function cleanupUser(user: E2EUser): Promise<void> {
  const stripeKey = process.env.STRIPE_SECRET_KEY;
  const clerkKey = process.env.CLERK_SECRET_KEY;
  if (!stripeKey) throw new Error('STRIPE_SECRET_KEY required for cleanupUser');
  if (!clerkKey) throw new Error('CLERK_SECRET_KEY required for cleanupUser');

  // 1. Stripe — cancels active subs then deletes the customer. Idempotent on
  //    missing customers (the helper just returns).
  await cancelSubsAndDeleteCustomer(stripeKey, user.email);

  // 2. Backend — DELETE /debug/user-data wipes DDB rows + EFS workspace +
  //    ECS service for this clerk user. Only 404 is treated as success
  //    (idempotent: the endpoint already ran for this user, or the dev
  //    backend doesn't have it deployed yet on a brand-new branch). Every
  //    other error MUST surface — silently swallowing teardown failures was
  //    leaking ECS services on every failed run (Codex P1 on PR #309).
  try {
    await user.api.delete('/debug/user-data');
  } catch (err) {
    // Match by structured status code, not message text — a 500 whose body
    // happens to contain "404" must NOT be silently swallowed (Codex P2 on
    // PR #309). AuthedFetchError exposes the actual response status.
    if (err instanceof AuthedFetchError && err.status === 404) {
      console.warn('[e2e] /debug/user-data 404 — treating as idempotent success');
    } else {
      throw err;
    }
  }

  // 3. Clerk — org first (if any), then the user. Both helpers treat 404 as
  //    success so re-running cleanup on a partially-torn-down user is safe.
  if (user.orgId) {
    await deleteOrg({ secretKey: clerkKey, orgId: user.orgId });
  }
  await deleteUser({ secretKey: clerkKey, userId: user.clerkUserId });

  // 4. Settle window — Stripe + Clerk are eventually consistent on the read
  //    side. 5s is enough in practice; a tighter poll would just add flakes.
  await new Promise((r) => setTimeout(r, 5000));

  // 5. Hard-fail verification. DDB / EFS are checked by the backend's
  //    DELETE response (it 200s only if it actually deleted everything), so
  //    we only re-query the external systems here.
  const stripeRemaining = await findCustomerByEmail(stripeKey, user.email);
  if (stripeRemaining) {
    throw new Error(`Stripe leak: customer ${stripeRemaining.id} not deleted`);
  }

  const clerkRemaining = await findUserByEmail({
    secretKey: clerkKey,
    email: user.email,
  });
  if (clerkRemaining) {
    throw new Error(`Clerk leak: user ${clerkRemaining.id} not deleted`);
  }
}

/**
 * Bare Playwright fixture export — intentionally throws. Specs should call
 * `createE2EUser` / `cleanupUser` directly in `beforeAll` / `afterAll` so the
 * role and (optional) orgId can be set per-spec. Kept as load-bearing
 * documentation for future contributors who go looking for `test.e2eUser`.
 */
export const test = base.extend<Record<string, never>, { e2eUser: E2EUser }>({
  e2eUser: [
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    async ({ browser: _browser }, use) => {
      void use;
      throw new Error(
        'Use createE2EUser(page, role) in beforeAll, not the bare e2eUser fixture',
      );
    },
    { scope: 'worker' },
  ],
});
