import { test, expect, type Page } from '@playwright/test';
import { clerk, clerkSetup, setupClerkTestingToken } from '@clerk/testing/playwright';
import { cancelSubscriptionIfExists, createSubscription, waitForSubscriptionActive } from './helpers/stripe';
import { deprovisionIfExists, waitForRunning } from './helpers/provision';

const DEV_STARTER_PRICE_ID = 'price_1TF5MDI54BysGS3rlT80MMI8';
const E2E_EMAIL = 'isol8-e2e-testing@mailsac.com';
const E2E_PASSWORD = 'InvincibleS4E5';
const BASE_URL = process.env.BASE_URL ?? 'http://localhost:3000';
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000/api/v1';

test.describe('E2E Gate: Full User Journey', () => {
  test.describe.configure({ mode: 'serial' });
  test.use({ retries: 0 }); // Destructive side effects — no retries

  let sharedPage: Page;
  let authToken = '';

  test.beforeAll(async ({ browser }) => {
    test.setTimeout(240_000); // sign-in + navigation can take 120s+ on CI
    // clerkSetup() sets process.env.CLERK_FAPI and CLERK_TESTING_TOKEN in THIS worker.
    // global.setup.ts calls clerkSetup() in the setup project worker, but Playwright workers
    // are separate processes — env vars don't cross process boundaries.
    await clerkSetup();
    // Create context with Vercel bypass header — browser.newPage() doesn't inherit extraHTTPHeaders
    const ctx = await browser.newContext({
      extraHTTPHeaders: process.env.VERCEL_AUTOMATION_BYPASS_SECRET
        ? { 'x-vercel-protection-bypass': process.env.VERCEL_AUTOMATION_BYPASS_SECRET }
        : {},
    });
    sharedPage = await ctx.newPage();
    // setupClerkTestingToken intercepts Clerk FAPI requests and appends the testing token.
    // This is needed for Clerk.client to initialize (non-null) in the browser — without it,
    // Clerk hangs on the dev-browser-missing handshake.
    await setupClerkTestingToken({ page: sharedPage });

    // Navigate to /chat — Clerk middleware triggers server-side handshake, sets __clerk_db_jwt
    // cookie, and redirects to /sign-in?redirect_url=%2Fchat.
    await sharedPage.goto(`${BASE_URL}/chat`, { waitUntil: 'domcontentloaded' });

    // Wait for sign-in page and for Clerk's <SignIn /> component to render.
    // The email input being visible confirms Clerk.client is properly initialized.
    await sharedPage.waitForURL(/\/sign-in/, { timeout: 30_000 });
    await sharedPage.getByPlaceholder('Enter your email address').waitFor({ timeout: 60_000 });

    // Diagnostic: check Clerk state before attempting sign-in
    const preState = await sharedPage.evaluate(() => {
      const w = window as Window & { Clerk?: { loaded?: boolean; client?: { signIn?: unknown } } };
      return { loaded: w.Clerk?.loaded, clientExists: w.Clerk?.client != null };
    });
    console.log('[e2e] Clerk state before signIn:', JSON.stringify(preState));

    // Try signIn.create() directly to see the sign-in status (complete vs needs_second_factor)
    const signInResult = await sharedPage.evaluate(async ({ email, password }) => {
      const w = window as Window & { Clerk?: { client?: { signIn: { create: (p: Record<string, string>) => Promise<{ id: string; status: string; createdSessionId: string | null }> } }; setActive: (p: { session: string | null }) => Promise<void> } };
      if (!w.Clerk?.client) return { error: 'Clerk.client is null' };
      try {
        const signIn = await w.Clerk.client.signIn.create({
          strategy: 'password', identifier: email, password: password,
        });
        if (signIn.createdSessionId) {
          await w.Clerk.setActive({ session: signIn.createdSessionId });
        }
        return { status: signIn.status, createdSessionId: signIn.createdSessionId };
      } catch (e: unknown) {
        return { error: String(e) };
      }
    }, { email: E2E_EMAIL, password: E2E_PASSWORD });
    console.log('[e2e] signIn.create() result:', JSON.stringify(signInResult));

    // Verify session was established
    const sessionId = await sharedPage.evaluate(() => {
      const w = window as Window & { Clerk?: { session?: { id?: string } } };
      return w.Clerk?.session?.id ?? null;
    });
    console.log('[e2e] Session ID after signIn:', sessionId);
    if (!sessionId) throw new Error(`[e2e] No session — signIn result: ${JSON.stringify(signInResult)}`);

    // Navigate to /chat now that we have an active session
    await sharedPage.goto(`${BASE_URL}/chat`, { waitUntil: 'domcontentloaded' });
    await sharedPage.waitForURL(/\/chat/, { timeout: 30_000 });

    // Retrieve auth token
    authToken = await sharedPage.waitForFunction(async () => {
      const win = window as Window & { Clerk?: { loaded?: boolean; session?: { getToken: () => Promise<string> } } };
      if (!win.Clerk?.loaded || !win.Clerk?.session?.getToken) return null;
      return (await win.Clerk.session.getToken()) || null;
    }, { timeout: 60_000 }).then(h => h.jsonValue()) as string;
  });

  test.afterAll(async () => {
    try { await cancelSubscriptionIfExists(E2E_EMAIL); } catch { /* ignore */ }
    try {
      if (authToken) await deprovisionIfExists(API_URL, authToken);
    } catch { /* ignore */ }
    await sharedPage?.context().close();
  });

  test('Step 1: Idempotent cleanup', async () => {
    test.setTimeout(4 * 60_000);
    await test.step('Cancel existing subscription if any', async () => {
      await cancelSubscriptionIfExists(E2E_EMAIL);
    }, { timeout: 60_000 });
    await test.step('Deprovision container if running', async () => {
      await deprovisionIfExists(API_URL, authToken);
    }, { timeout: 60_000 });
  });

  test('Step 2: Auth', async () => {
    test.setTimeout(60_000);
    await test.step('Navigate to /chat and verify authenticated', async () => {
      await sharedPage.goto(`${BASE_URL}/chat`);
      await expect(sharedPage).toHaveURL(/\/chat/);
    }, { timeout: 60_000 });
  });

  test('Step 3: Subscribe', async () => {
    test.setTimeout(4 * 60_000);
    await test.step('Create Stripe subscription via API', async () => {
      await createSubscription(E2E_EMAIL, DEV_STARTER_PRICE_ID);
    }, { timeout: 60_000 });
    await test.step('Wait for subscription to propagate to backend', async () => {
      await waitForSubscriptionActive(API_URL, authToken, 120_000);
    }, { timeout: 130_000 });
  });

  test('Step 4: Provision container', async () => {
    test.setTimeout(14 * 60_000);
    await test.step('Trigger provisioning', async () => {
      const res = await sharedPage.evaluate(async (apiUrl) => {
        const win = window as Window & { Clerk?: { session?: { getToken: () => Promise<string> } } };
        const token = await win.Clerk?.session?.getToken();
        const r = await fetch(`${apiUrl}/debug/provision`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
        });
        return r.status;
      }, API_URL);
      expect(res).toBe(200);
    }, { timeout: 60_000 });
    await test.step('Wait for container to reach running state', async () => {
      await waitForRunning(API_URL, authToken, 10 * 60_000);
    }, { timeout: 12 * 60_000 });
  });

  test('Step 5: Chat', async () => {
    test.setTimeout(6 * 60_000);
    await test.step('Navigate to /chat', async () => {
      await sharedPage.goto(`${BASE_URL}/chat`);
    }, { timeout: 60_000 });
    await test.step('Select first agent', async () => {
      // Selector from ChatLayout.tsx — agent list items use the .agent-item CSS class
      const agentItem = sharedPage.locator('.agent-item').first();
      await agentItem.waitFor({ timeout: 60_000 });
      await agentItem.click();
    }, { timeout: 60_000 });
    await test.step('Send ping message', async () => {
      const textarea = sharedPage.getByPlaceholderText('Ask anything');
      await textarea.fill('ping');
      await textarea.press('Enter');
    }, { timeout: 30_000 });
    await test.step('Verify assistant responds', async () => {
      const assistantMsg = sharedPage.locator('[data-role="assistant"]').last();
      await expect(assistantMsg).toBeVisible({ timeout: 120_000 });
      await expect(assistantMsg).toContainText(/pong/i, { timeout: 120_000 });
    }, { timeout: 4 * 60_000 });
  });
});
