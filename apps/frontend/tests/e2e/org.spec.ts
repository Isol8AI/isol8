import { test, expect } from '@playwright/test';
import { clerkSetup, setupClerkTestingToken } from '@clerk/testing/playwright';
import { createE2EUser, cleanupUser, type E2EUser } from './fixtures/user';
import { signIn } from './drivers/sign-in';
import { onboardOrganization } from './drivers/onboarding';
import { completeStripeCheckout } from './drivers/stripe-checkout';
import {
  waitForChatReady,
  sendMessageAndWaitForResponse,
} from './drivers/chat';
import { billingTier, isSubscribed } from './assertions/billing';
import { containerHealthy } from './assertions/container';
import { modelUsed } from './assertions/chat';

test.describe('E2E: Org happy path', () => {
  test.describe.configure({ mode: 'serial' });
  // Same as personal.spec — Step 3 cold-start can hit 20 min when scale-to-zero
  // races the gateway WS handshake.
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
    user = await createE2EUser(page, 'org');
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

  test('Step 2: organization onboarding', async () => {
    // Record orgId on `user` the instant Clerk reports it, BEFORE the
    // /chat redirect wait — otherwise a downstream UI failure here would
    // leak the org because afterAll's cleanupUser would skip deleteOrg
    // (Codex P1 on PR #309).
    await onboardOrganization(user.page, `e2e-org-${user.runId}`, (orgId) => {
      user.orgId = orgId;
    });
    expect(user.page.url()).toContain('/chat');
  });

  test('Step 3: free-tier chat (org context)', async () => {
    await containerHealthy(user.api, { timeoutMs: 10 * 60_000 });
    await waitForChatReady(user.page);
    await sendMessageAndWaitForResponse(user.page, 'Say "hello" and nothing else.');
  });

  test('Step 4: upgrade to Starter via real Stripe Checkout', async () => {
    await user.page.goto('/settings');
    await user.page.getByRole('tab', { name: 'Billing' }).click();
    await user.page.getByRole('button', { name: 'Subscribe to Starter' }).click();
    await completeStripeCheckout(user.page, user.email);
    await isSubscribed(user.api, true);
    await billingTier(user.api, 'starter');
  });

  test('Step 5: starter-tier chat (org context)', async () => {
    await waitForChatReady(user.page);
    await sendMessageAndWaitForResponse(user.page, 'Say "hi" and nothing else.');
    await modelUsed(user.api, 'qwen.qwen3-vl-235b-a22b');
  });
});
