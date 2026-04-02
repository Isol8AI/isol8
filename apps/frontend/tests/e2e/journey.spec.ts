import { test, expect, type Page } from '@playwright/test';
import { clerk } from '@clerk/testing/playwright';
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
    test.setTimeout(120_000); // sign-in + navigation + networkidle can take 60s+ on CI
    sharedPage = await browser.newPage();
    await sharedPage.goto(BASE_URL);
    await clerk.signIn({
      page: sharedPage,
      signInParams: {
        strategy: 'password',
        identifier: E2E_EMAIL,
        password: E2E_PASSWORD,
      },
    });
    // Navigate to /chat and wait for all JS-triggered redirects to settle
    await sharedPage.goto(`${BASE_URL}/chat`);
    await sharedPage.waitForLoadState('networkidle', { timeout: 20_000 });
    // Wait for Clerk to finish initializing the session (safe now — page is stable)
    await sharedPage.waitForFunction(() => {
      const win = window as Window & { Clerk?: { session?: { getToken: () => Promise<string> } } };
      return !!win.Clerk?.session?.getToken;
    }, { timeout: 15_000 });
    authToken = await sharedPage.evaluate(async () => {
      const win = window as Window & { Clerk?: { session?: { getToken: () => Promise<string> } } };
      return (await win.Clerk?.session?.getToken()) ?? '';
    });
  });

  test.afterAll(async () => {
    try { await cancelSubscriptionIfExists(E2E_EMAIL); } catch { /* ignore */ }
    try {
      if (authToken) await deprovisionIfExists(API_URL, authToken);
    } catch { /* ignore */ }
    await sharedPage?.close();
  });

  test('Step 1: Idempotent cleanup', async () => {
    test.setTimeout(2 * 60_000);
    await test.step('Cancel existing subscription if any', async () => {
      await cancelSubscriptionIfExists(E2E_EMAIL);
    }, { timeout: 30_000 });
    await test.step('Deprovision container if running', async () => {
      await deprovisionIfExists(API_URL, authToken);
    }, { timeout: 30_000 });
  });

  test('Step 2: Auth', async () => {
    test.setTimeout(30_000);
    await test.step('Navigate to /chat and verify authenticated', async () => {
      await sharedPage.goto(`${BASE_URL}/chat`);
      await expect(sharedPage).toHaveURL(/\/chat/);
    }, { timeout: 30_000 });
  });

  test('Step 3: Subscribe', async () => {
    test.setTimeout(2 * 60_000);
    await test.step('Create Stripe subscription via API', async () => {
      await createSubscription(E2E_EMAIL, DEV_STARTER_PRICE_ID);
    }, { timeout: 30_000 });
    await test.step('Wait for subscription to propagate to backend', async () => {
      await waitForSubscriptionActive(API_URL, authToken, 60_000);
    }, { timeout: 65_000 });
  });

  test('Step 4: Provision container', async () => {
    test.setTimeout(7 * 60_000);
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
    }, { timeout: 30_000 });
    await test.step('Wait for container to reach running state', async () => {
      await waitForRunning(API_URL, authToken, 5 * 60_000);
    }, { timeout: 6 * 60_000 });
  });

  test('Step 5: Chat', async () => {
    test.setTimeout(3 * 60_000);
    await test.step('Navigate to /chat', async () => {
      await sharedPage.goto(`${BASE_URL}/chat`);
    }, { timeout: 30_000 });
    await test.step('Select first agent', async () => {
      // Selector from ChatLayout.tsx — agent list items use the .agent-item CSS class
      const agentItem = sharedPage.locator('.agent-item').first();
      await agentItem.waitFor({ timeout: 30_000 });
      await agentItem.click();
    }, { timeout: 30_000 });
    await test.step('Send ping message', async () => {
      const textarea = sharedPage.getByPlaceholderText('Ask anything');
      await textarea.fill('ping');
      await textarea.press('Enter');
    }, { timeout: 15_000 });
    await test.step('Verify assistant responds', async () => {
      const assistantMsg = sharedPage.locator('[data-role="assistant"]').last();
      await expect(assistantMsg).toBeVisible({ timeout: 60_000 });
      await expect(assistantMsg).toContainText(/pong/i, { timeout: 60_000 });
    }, { timeout: 2 * 60_000 });
  });
});
