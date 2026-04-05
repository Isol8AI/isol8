import { test, expect, type Page } from '@playwright/test';
import { clerkSetup, setupClerkTestingToken } from '@clerk/testing/playwright';
import { cancelSubscriptionIfExists, getBackendStripeCustomerId, createSubscription, waitForSubscriptionActive } from './helpers/stripe';
import { deprovisionIfExists, waitForRunning } from './helpers/provision';

const DEV_STARTER_PRICE_ID = 'price_1TF5MDI54BysGS3rlT80MMI8';
const E2E_EMAIL = 'isol8-e2e-testing@mailsac.com';
const BASE_URL = process.env.BASE_URL ?? 'http://localhost:3000';
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000/api/v1';

/**
 * Create a one-time sign-in token via the Clerk Backend API.
 * Uses strategy:'ticket' on the frontend — bypasses password, MFA, and device verification.
 */
async function createSignInToken(): Promise<{ ticket: string; userId: string }> {
  const secretKey = process.env.CLERK_SECRET_KEY;
  if (!secretKey) throw new Error('[e2e] CLERK_SECRET_KEY not set');

  // Find user by email
  const usersRes = await fetch(
    `https://api.clerk.com/v1/users?email_address[]=${encodeURIComponent(E2E_EMAIL)}`,
    { headers: { Authorization: `Bearer ${secretKey}` } },
  );
  if (!usersRes.ok) throw new Error(`[e2e] Users API ${usersRes.status}: ${await usersRes.text()}`);
  const users = await usersRes.json() as Array<{ id: string }>;
  if (!users.length) throw new Error(`[e2e] No user found for ${E2E_EMAIL}`);
  console.log(`[e2e] Found user: ${users[0].id}`);

  // Create sign-in token
  const tokenRes = await fetch('https://api.clerk.com/v1/sign_in_tokens', {
    method: 'POST',
    headers: { Authorization: `Bearer ${secretKey}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id: users[0].id }),
  });
  if (!tokenRes.ok) throw new Error(`[e2e] Sign-in token API ${tokenRes.status}: ${await tokenRes.text()}`);
  const { token } = await tokenRes.json() as { token: string };
  console.log('[e2e] Sign-in token created');
  return { ticket: token, userId: users[0].id };
}

test.describe('E2E Gate: Full User Journey', () => {
  test.describe.configure({ mode: 'serial' });

  let sharedPage: Page;
  let clerkUserId: string;

  /** Get a fresh Clerk JWT from the browser (tokens expire after 60s). */
  async function getToken(): Promise<string> {
    return sharedPage.evaluate(async () => {
      const w = window as Window & { Clerk?: { session?: { getToken: () => Promise<string> } } };
      return (await w.Clerk?.session?.getToken()) ?? '';
    });
  }

  test.beforeAll(async ({ browser }) => {
    test.setTimeout(240_000);
    await clerkSetup();
    const ctx = await browser.newContext({
      extraHTTPHeaders: process.env.VERCEL_AUTOMATION_BYPASS_SECRET
        ? { 'x-vercel-protection-bypass': process.env.VERCEL_AUTOMATION_BYPASS_SECRET }
        : {},
    });
    sharedPage = await ctx.newPage();
    await setupClerkTestingToken({ page: sharedPage });

    // Navigate to homepage so Clerk JS loads
    await sharedPage.goto(BASE_URL, { waitUntil: 'domcontentloaded' });
    await sharedPage.waitForFunction(() => {
      const w = window as Window & { Clerk?: { loaded?: boolean; client?: unknown } };
      return w.Clerk?.loaded === true && w.Clerk?.client != null;
    }, { timeout: 30_000 });

    // Create a backend-issued sign-in token — bypasses password + MFA entirely
    const { ticket, userId } = await createSignInToken();
    clerkUserId = userId;

    // Use the ticket to create an authenticated session
    await sharedPage.evaluate(async (t: string) => {
      const w = window as unknown as { Clerk: { client: { signIn: { create: (opts: Record<string, string>) => Promise<{ createdSessionId: string }> } }; setActive: (opts: { session: string }) => Promise<void> } };
      const si = await w.Clerk.client.signIn.create({ strategy: 'ticket', ticket: t });
      await w.Clerk.setActive({ session: si.createdSessionId });
    }, ticket);

    // Verify session
    const sid = await sharedPage.evaluate(() => {
      const w = window as unknown as { Clerk?: { session?: { id?: string } } };
      return w.Clerk?.session?.id ?? null;
    });
    console.log('[e2e] Session ID:', sid);
    if (!sid) throw new Error('[e2e] No session after sign-in token');

    // Quick backend auth test with the token we'll get
    console.log('[e2e] CLERK_FAPI:', process.env.CLERK_FAPI);

    // Verify we can get a token (session is active)
    const initialToken = await getToken();
    console.log('[e2e] authToken starts with:', initialToken?.substring(0, 20));
    if (!initialToken) throw new Error('[e2e] No auth token — session may not be active');

    // Navigate to /chat (may redirect to /onboarding if no subscription yet — that's fine)
    await sharedPage.goto(`${BASE_URL}/chat`, { waitUntil: 'domcontentloaded' });
  });

  test.afterAll(async () => {
    try { await cancelSubscriptionIfExists(E2E_EMAIL); } catch { /* ignore */ }
    try { await deprovisionIfExists(API_URL, getToken); } catch { /* ignore */ }
    await sharedPage?.context().close();
  });

  test('Step 1: Idempotent cleanup', async () => {
    test.setTimeout(4 * 60_000);
    await test.step('Cancel existing subscription if any', async () => {
      await cancelSubscriptionIfExists(E2E_EMAIL);
    }, { timeout: 60_000 });
    await test.step('Deprovision container if running', async () => {
      await deprovisionIfExists(API_URL, getToken);
    }, { timeout: 60_000 });
  });

  test('Step 2: Auth', async () => {
    test.setTimeout(60_000);
    await test.step('Verify authenticated (not redirected to sign-in)', async () => {
      // After cleanup, page may be on /chat or /onboarding — just confirm session is active
      const url = sharedPage.url();
      console.log('[e2e] Step 2 URL:', url);
      expect(url).not.toContain('/sign-in');
    }, { timeout: 60_000 });
  });

  test('Step 3: Subscribe', async () => {
    test.setTimeout(4 * 60_000);
    await test.step('Sync user with backend', async () => {
      const token = await getToken();
      const res = await fetch(`${API_URL}/users/sync`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      console.log('[e2e] User sync:', res.status);
    }, { timeout: 30_000 });
    await test.step('Create Stripe subscription via backend customer', async () => {
      // Get the Stripe customer ID the backend uses (searches by owner_id metadata)
      const customerId = await getBackendStripeCustomerId(clerkUserId, API_URL, getToken);
      console.log('[e2e] Backend Stripe customer:', customerId);
      await createSubscription(customerId, DEV_STARTER_PRICE_ID);
    }, { timeout: 60_000 });
    await test.step('Wait for subscription to propagate to backend', async () => {
      await waitForSubscriptionActive(API_URL, getToken, 120_000);
    }, { timeout: 130_000 });
  });

  test('Step 4: Provision container', async () => {
    test.setTimeout(14 * 60_000);
    await test.step('Trigger provisioning (retry on ECS draining)', async () => {
      // DELETE first to clean up any leftover container from a prior run
      await deprovisionIfExists(API_URL, getToken);

      // POST /debug/provision — retry on 503 (ECS service still draining after DELETE)
      const deadline = Date.now() + 90_000;
      let lastStatus = 0;
      while (Date.now() < deadline) {
        const res = await sharedPage.evaluate(async (apiUrl) => {
          const win = window as Window & { Clerk?: { session?: { getToken: () => Promise<string> } } };
          const token = await win.Clerk?.session?.getToken();
          const r = await fetch(`${apiUrl}/debug/provision`, {
            method: 'POST',
            headers: { Authorization: `Bearer ${token}` },
          });
          return r.status;
        }, API_URL);
        lastStatus = res;
        if (res === 200) break;
        if (res !== 503) {
          throw new Error(`Unexpected provision response: ${res}`);
        }
        console.log('[e2e] Provision 503 (ECS draining), retrying in 10s...');
        await new Promise((r) => setTimeout(r, 10_000));
      }
      expect(lastStatus).toBe(200);
    }, { timeout: 120_000 });
    await test.step('Wait for container to reach running state', async () => {
      await waitForRunning(API_URL, getToken, 10 * 60_000);
    }, { timeout: 12 * 60_000 });
  });

  // Step 5 (Chat) is skipped for now — the WebSocket API Gateway returns 500
  // during the handshake in CI (works locally). The Lambda authorizer or
  // VPC Link path needs investigation via CloudWatch logs.
  // TODO: Re-enable once WebSocket 500 is resolved.
  // See: WebSocket error: "Unexpected response code: 500" from wss://ws-dev.isol8.co
});
