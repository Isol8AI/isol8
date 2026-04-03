import { test, expect, type Page } from '@playwright/test';
import { clerkSetup, setupClerkTestingToken } from '@clerk/testing/playwright';
import { cancelSubscriptionIfExists, createSubscription, waitForSubscriptionActive } from './helpers/stripe';
import { deprovisionIfExists, waitForRunning } from './helpers/provision';

const DEV_STARTER_PRICE_ID = 'price_1TF5MDI54BysGS3rlT80MMI8';
const E2E_EMAIL = 'isol8-e2e-testing@mailsac.com';
const E2E_PASSWORD = 'InvincibleS4E5';
const BASE_URL = process.env.BASE_URL ?? 'http://localhost:3000';
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000/api/v1';

/**
 * Reads the latest Clerk verification code from the mailsac public inbox via REST API.
 * Polls until a recent email from Clerk arrives with a 6-digit verification code.
 */
async function readOtpFromMailsac(): Promise<string> {
  const address = 'isol8-e2e-testing@mailsac.com';
  const apiKey = process.env.MAILSAC_API_KEY ?? '';
  const headers: Record<string, string> = apiKey ? { 'Mailsac-Key': apiKey } : {};
  const startTime = Date.now();
  const timeout = 60_000;

  while (Date.now() - startTime < timeout) {
    const res = await fetch(`https://mailsac.com/api/addresses/${address}/messages`, { headers });
    if (res.ok) {
      const messages = await res.json() as Array<{ _id: string; subject?: string; receivedAt?: string }>;
      // Find latest email with a Clerk-like subject (e.g., "Your verification code")
      if (messages.length > 0) {
        const latest = messages[0]; // mailsac returns newest first
        // Fetch the text body of the latest message
        const bodyRes = await fetch(`https://mailsac.com/api/text/${address}/${latest._id}`, { headers });
        if (bodyRes.ok) {
          const bodyText = await bodyRes.text();
          const match = bodyText.match(/\b(\d{6})\b/);
          if (match) {
            console.log(`[e2e] Extracted OTP from mailsac: ${match[1]} (subject: ${latest.subject})`);
            return match[1];
          }
          console.log(`[e2e] No 6-digit code in latest email (subject: ${latest.subject}), retrying...`);
        }
      }
    } else {
      console.log(`[e2e] Mailsac API ${res.status}: ${await res.text().catch(() => 'no body')}`);
    }
    // Wait 3 seconds before polling again
    await new Promise(r => setTimeout(r, 3_000));
  }
  throw new Error('[e2e] Timed out waiting for OTP email from mailsac');
}

test.describe('E2E Gate: Full User Journey', () => {
  test.describe.configure({ mode: 'serial' });
  test.use({ retries: 0 }); // Destructive side effects — no retries

  let sharedPage: Page;
  let authToken = '';

  test.beforeAll(async ({ browser }) => {
    test.setTimeout(240_000); // sign-in + navigation can take 120s+ on CI
    // clerkSetup() sets process.env.CLERK_FAPI and CLERK_TESTING_TOKEN in THIS worker.
    await clerkSetup();
    // Create context with Vercel bypass header
    const ctx = await browser.newContext({
      extraHTTPHeaders: process.env.VERCEL_AUTOMATION_BYPASS_SECRET
        ? { 'x-vercel-protection-bypass': process.env.VERCEL_AUTOMATION_BYPASS_SECRET }
        : {},
    });
    sharedPage = await ctx.newPage();
    // setupClerkTestingToken allows Clerk.client to initialize (non-null).
    await setupClerkTestingToken({ page: sharedPage });

    // Navigate to /chat — middleware triggers handshake, redirects to /sign-in
    await sharedPage.goto(`${BASE_URL}/chat`, { waitUntil: 'domcontentloaded' });
    await sharedPage.waitForURL(/\/sign-in/, { timeout: 30_000 });
    // Wait for Clerk's <SignIn /> form to render
    await sharedPage.getByPlaceholder('Enter your email address').waitFor({ timeout: 60_000 });

    // Sign in with password — Clerk returns needs_second_factor (new-device email verification).
    // Testing tokens do NOT bypass this. We complete it by reading the OTP from mailsac.
    const signInResult = await sharedPage.evaluate(async ({ email, password }) => {
      const w = window as Window & { Clerk?: { client?: { signIn: { create: (p: Record<string, string>) => Promise<{ status: string; createdSessionId: string | null; prepareSecondFactor: (p: Record<string, string>) => Promise<unknown> }> } }; setActive: (p: { session: string | null }) => Promise<void> } };
      const signIn = await w.Clerk!.client!.signIn.create({
        strategy: 'password', identifier: email, password: password,
      });
      if (signIn.status === 'needs_second_factor') {
        // Trigger Clerk to send the email OTP
        await signIn.prepareSecondFactor({ strategy: 'email_code' });
        return { status: 'needs_second_factor' };
      }
      if (signIn.createdSessionId) {
        await w.Clerk!.setActive({ session: signIn.createdSessionId });
        return { status: 'complete' };
      }
      return { status: signIn.status };
    }, { email: E2E_EMAIL, password: E2E_PASSWORD });
    console.log('[e2e] signIn result:', JSON.stringify(signInResult));

    if (signInResult.status === 'needs_second_factor') {
      // Read the OTP from the mailsac inbox
      const otp = await readOtpFromMailsac();

      // Complete the second factor
      const secondResult = await sharedPage.evaluate(async (code) => {
        const w = window as Window & { Clerk?: { client?: { signIn: { attemptSecondFactor: (p: Record<string, string>) => Promise<{ status: string; createdSessionId: string | null }> } }; setActive: (p: { session: string | null }) => Promise<void> } };
        const result = await w.Clerk!.client!.signIn.attemptSecondFactor({
          strategy: 'email_code', code,
        });
        if (result.createdSessionId) {
          await w.Clerk!.setActive({ session: result.createdSessionId });
        }
        return { status: result.status, hasSession: !!result.createdSessionId };
      }, otp);
      console.log('[e2e] secondFactor result:', JSON.stringify(secondResult));
      if (secondResult.status !== 'complete') {
        throw new Error(`[e2e] Second factor failed: ${JSON.stringify(secondResult)}`);
      }
    }

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
