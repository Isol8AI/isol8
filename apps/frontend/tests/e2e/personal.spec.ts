import { test, expect } from '@playwright/test';
import { clerkSetup, setupClerkTestingToken } from '@clerk/testing/playwright';
import { createE2EUser, cleanupUser, type E2EUser } from './fixtures/user';
import { signIn } from './drivers/sign-in';
import { onboardPersonal } from './drivers/onboarding';
import { completeStripeCheckout } from './drivers/stripe-checkout';
import {
  waitForChatReady,
  sendMessageAndWaitForResponse,
} from './drivers/chat';
import { billingTier, isSubscribed } from './assertions/billing';
import { containerHealthy } from './assertions/container';
import { modelUsed } from './assertions/chat';

test.describe('E2E: Personal happy path', () => {
  test.describe.configure({ mode: 'serial' });
  // Per-test cap. Step 3 alone can hit 20 min on a free-tier cold start
  // that scale-to-zeros mid-handshake (containerHealthy 10m + waitForChatReady
  // 10m + chat round-trip 90s). 25 min gives headroom; the slow path
  // dominates in practice.
  test.setTimeout(25 * 60_000);

  let user: E2EUser;

  test.beforeAll(async ({ browser }) => {
    await clerkSetup();
    const ctx = await browser.newContext({
      extraHTTPHeaders: process.env.VERCEL_AUTOMATION_BYPASS_SECRET
        ? { 'x-vercel-protection-bypass': process.env.VERCEL_AUTOMATION_BYPASS_SECRET }
        : {},
    });
    const page = await ctx.newPage();
    await setupClerkTestingToken({ page });
    user = await createE2EUser(page, 'personal');
    console.log(
      `[e2e] runId=${user.runId} clerkUserId=${user.clerkUserId} email=${user.email}`,
    );
  });

  test.afterAll(async () => {
    if (user) await cleanupUser(user);
  });

  test('Step 1: sign in', async () => {
    if (!process.env.BASE_URL) throw new Error('BASE_URL is required');
    await signIn(user.page, process.env.BASE_URL, user.clerkUserId);
    expect(user.page.url()).not.toContain('/sign-in');
  });

  test('Step 2: personal onboarding', async () => {
    await onboardPersonal(user.page);
    expect(user.page.url()).toContain('/chat');
  });

  test('Step 3: free-tier chat', async () => {
    await containerHealthy(user.api, { timeoutMs: 10 * 60_000 });
    await waitForChatReady(user.page);
    await sendMessageAndWaitForResponse(user.page, 'Say "hello" and nothing else.');
  });

  test('Step 4: upgrade to Starter via real Stripe Checkout', async () => {
    await user.page.goto('/settings');
    // Settings is a single-route SPA with state-driven panels; click the
    // Billing tab to render the plan cards.
    await user.page.getByRole('tab', { name: 'Billing' }).click();
    await user.page.getByRole('button', { name: 'Subscribe to Starter' }).click();
    await completeStripeCheckout(user.page, user.email);
    await isSubscribed(user.api, true);
    await billingTier(user.api, 'starter');
  });

  test('Step 5: starter-tier chat (verifies model swap)', async () => {
    await waitForChatReady(user.page);
    await sendMessageAndWaitForResponse(user.page, 'Say "hi" and nothing else.');
    await modelUsed(user.api, 'qwen.qwen3-vl-235b-a22b');
  });
});
