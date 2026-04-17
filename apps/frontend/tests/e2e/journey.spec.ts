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

  /** Get a fresh Clerk JWT from the browser (tokens expire after 60s).
   *  Waits for Clerk to be loaded and session to exist before requesting. */
  async function getToken(): Promise<string> {
    // Ensure Clerk is loaded on the current page (may have navigated)
    await sharedPage.waitForFunction(() => {
      const w = window as Window & { Clerk?: { loaded?: boolean; session?: unknown } };
      return w.Clerk?.loaded === true && w.Clerk?.session != null;
    }, { timeout: 30_000 });

    return sharedPage.evaluate(async () => {
      const w = window as Window & { Clerk?: { session?: { getToken: () => Promise<string> } } };
      return (await w.Clerk?.session?.getToken()) ?? '';
    });
  }

  test.beforeAll(async ({ browser }) => {
    test.setTimeout(240_000);
    // Defense in depth: cancel any leftover subscription before we do anything else,
    // in case a previous run crashed without running afterAll cleanup.
    try {
      await cancelSubscriptionIfExists(E2E_EMAIL);
    } catch (err) {
      console.error('[e2e] beforeAll pre-cleanup cancelSubscriptionIfExists failed (non-fatal):', err);
    }
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
    // Retry cancellation up to 3 times with exponential backoff. If all retries
    // fail, log loudly so a human can clean up manually — but do not throw, since
    // the test itself may have passed and we don't want to mask the real result.
    const backoffs = [1_000, 2_000, 4_000];
    let lastErr: unknown;
    for (let attempt = 0; attempt < backoffs.length; attempt++) {
      try {
        await cancelSubscriptionIfExists(E2E_EMAIL);
        lastErr = undefined;
        break;
      } catch (err) {
        lastErr = err;
        console.error(`[e2e] afterAll cancelSubscriptionIfExists attempt ${attempt + 1} failed:`, err);
        if (attempt < backoffs.length - 1) {
          await new Promise((r) => setTimeout(r, backoffs[attempt]));
        }
      }
    }
    if (lastErr !== undefined) {
      console.error(
        `[e2e] CRITICAL: afterAll cleanup FAILED after ${backoffs.length} retries for ${E2E_EMAIL}. ` +
          `A subscription may be leaked. Manual cleanup required. Last error:`,
        lastErr,
      );
    }
    // Don't deprovision — leave the container running for the next run.
    // This avoids triggering ECS drain cycles that cause long timeouts.
    await sharedPage?.context().close();
  });

  test('Step 1: Idempotent cleanup', async () => {
    test.setTimeout(2 * 60_000);
    await test.step('Cancel existing subscription if any', async () => {
      await cancelSubscriptionIfExists(E2E_EMAIL);
    }, { timeout: 60_000 });
    // Note: we intentionally do NOT deprovision the container here.
    // The CDK pipeline deploys the ECS service before E2EGate runs,
    // which already triggers a rolling update. Deprovisioning would
    // start a second drain cycle, causing long timeouts.
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

      // Diagnostic: decode JWT claims (no verification) to debug 401
      try {
        const [, payloadB64] = token.split('.');
        const claims = JSON.parse(Buffer.from(payloadB64, 'base64url').toString());
        console.log('[e2e] JWT claims: iss=%s sub=%s aud=%s azp=%s exp=%s nbf=%s',
          claims.iss, claims.sub, claims.aud, claims.azp, claims.exp, claims.nbf);
        console.log('[e2e] JWT full claims:', JSON.stringify(claims));
      } catch (e) { console.log('[e2e] JWT decode error:', e); }

      const res = await fetch(`${API_URL}/users/sync`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      console.log('[e2e] User sync:', res.status);
      if (!res.ok) {
        const body = await res.text();
        console.log('[e2e] User sync error body:', body);
      }
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
    await test.step('Ensure container exists', async () => {
      // POST /debug/provision is idempotent — returns 200 if already provisioned.
      // Retry on 503 (ECS service still rolling from CDK deploy).
      const deadline = Date.now() + 3 * 60_000;
      let lastStatus = 0;
      while (Date.now() < deadline) {
        const token = await getToken();
        const res = await fetch(`${API_URL}/debug/provision`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
        });
        lastStatus = res.status;
        if (res.status === 200) break;
        if (res.status !== 503) {
          throw new Error(`Unexpected provision response: ${res.status}`);
        }
        console.log('[e2e] Provision 503 (ECS rolling), retrying in 10s...');
        await new Promise((r) => setTimeout(r, 10_000));
      }
      if (lastStatus !== 200) {
        throw new Error(`Provision failed: last status ${lastStatus} after 3 min of retries`);
      }
    }, { timeout: 4 * 60_000 });
    await test.step('Wait for gateway healthy', async () => {
      await waitForRunning(API_URL, getToken, 10 * 60_000);
    }, { timeout: 12 * 60_000 });
  });

  test('Step 5: Chat', async () => {
    test.setTimeout(3 * 60_000);

    await test.step('Navigate to /chat and wait for WebSocket connection', async () => {
      // Ensure we're on the chat page
      if (!sharedPage.url().includes('/chat')) {
        await sharedPage.goto(`${BASE_URL}/chat`, { waitUntil: 'domcontentloaded' });
      }

      // Wait for "Connected" indicator — means the WebSocket handshake succeeded
      // and the gateway pool is healthy.
      await sharedPage.getByText('Connected').waitFor({ state: 'visible', timeout: 60_000 });
    }, { timeout: 90_000 });

    await test.step('Send a message and receive a response', async () => {
      // Type a simple message into the chat input
      const input = sharedPage.getByPlaceholder('Ask anything');
      await input.waitFor({ state: 'visible', timeout: 10_000 });
      await input.fill('Say "hello" and nothing else.');

      // Click send
      await sharedPage.getByTestId('send-button').click();

      // Wait for an assistant response. Messages have data-role="assistant".
      const assistantMsg = sharedPage.locator('[data-role="assistant"]').last();
      await assistantMsg.waitFor({ state: 'visible', timeout: 90_000 });
      // Verify it has some text content (not an empty/error state)
      await expect(assistantMsg).not.toBeEmpty();
    }, { timeout: 120_000 });
  });
});
