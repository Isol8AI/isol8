import { test, expect, type Page } from '@playwright/test';
import { clerkSetup, setupClerkTestingToken } from '@clerk/testing/playwright';
import { waitForRunning } from './helpers/provision';
import { markUserOnboarded } from './helpers/clerk';
import { dismissChannelSetupIfPresent } from './helpers/onboarding';

const E2E_EMAIL = 'isol8-e2e-testing@mailsac.com';
const BASE_URL = process.env.BASE_URL ?? 'http://localhost:3000';
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000/api/v1';

/**
 * Create a one-time sign-in ticket via the Clerk Backend API so the browser
 * can start an authenticated session without running a password/MFA flow.
 */
async function createSignInToken(): Promise<{ ticket: string; userId: string }> {
  const secretKey = process.env.CLERK_SECRET_KEY;
  if (!secretKey) throw new Error('[smoke] CLERK_SECRET_KEY not set');

  // Clerk's ?email_address[]=X filter is unreliable — verified 2026-04-17
  // it returned ALL users regardless of the param. Match in JS to avoid
  // signing in as the wrong user.
  const usersRes = await fetch(
    `https://api.clerk.com/v1/users?email_address[]=${encodeURIComponent(E2E_EMAIL)}`,
    { headers: { Authorization: `Bearer ${secretKey}` } },
  );
  if (!usersRes.ok) throw new Error(`[smoke] Users API ${usersRes.status}: ${await usersRes.text()}`);
  const allUsers = await usersRes.json() as Array<{
    id: string;
    email_addresses?: Array<{ email_address?: string }>;
  }>;
  const matched = allUsers.find((u) =>
    u.email_addresses?.some((e) => e.email_address?.toLowerCase() === E2E_EMAIL.toLowerCase()),
  );
  if (!matched) {
    throw new Error(
      `[smoke] No Clerk user with email ${E2E_EMAIL} (Clerk returned ${allUsers.length} candidates, none matched)`,
    );
  }

  const tokenRes = await fetch('https://api.clerk.com/v1/sign_in_tokens', {
    method: 'POST',
    headers: { Authorization: `Bearer ${secretKey}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id: matched.id }),
  });
  if (!tokenRes.ok) throw new Error(`[smoke] Sign-in token API ${tokenRes.status}: ${await tokenRes.text()}`);
  const { token } = await tokenRes.json() as { token: string };
  return { ticket: token, userId: matched.id };
}

test.describe('Chat Smoke', () => {
  test.describe.configure({ mode: 'serial' });

  let sharedPage: Page;

  async function getToken(): Promise<string> {
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
    test.setTimeout(90_000);
    await clerkSetup();
    const ctx = await browser.newContext({
      extraHTTPHeaders: process.env.VERCEL_AUTOMATION_BYPASS_SECRET
        ? { 'x-vercel-protection-bypass': process.env.VERCEL_AUTOMATION_BYPASS_SECRET }
        : {},
    });
    sharedPage = await ctx.newPage();
    await setupClerkTestingToken({ page: sharedPage });

    await sharedPage.goto(BASE_URL, { waitUntil: 'domcontentloaded' });
    await sharedPage.waitForFunction(() => {
      const w = window as Window & { Clerk?: { loaded?: boolean; client?: unknown } };
      return w.Clerk?.loaded === true && w.Clerk?.client != null;
    }, { timeout: 30_000 });

    const { ticket, userId } = await createSignInToken();

    // Ensure ChatLayout doesn't render ProvisioningStepper over the chat.
    // See helpers/clerk.ts for why this flag can drift to false.
    await markUserOnboarded(userId);

    await sharedPage.evaluate(async (t: string) => {
      const w = window as unknown as {
        Clerk: {
          client: { signIn: { create: (opts: Record<string, string>) => Promise<{ createdSessionId: string }> } };
          setActive: (opts: { session: string }) => Promise<void>;
        };
      };
      const si = await w.Clerk.client.signIn.create({ strategy: 'ticket', ticket: t });
      await w.Clerk.setActive({ session: si.createdSessionId });
    }, ticket);
  });

  test.afterAll(async () => {
    await sharedPage?.context().close();
  });

  test('Steady-state precheck: subscription + container healthy', async () => {
    test.setTimeout(3 * 60_000);

    await test.step('E2E account is subscribed', async () => {
      const token = await getToken();
      const res = await fetch(`${API_URL}/billing/account`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`GET /billing/account failed: ${res.status}`);
      const data = await res.json();
      if (data.is_subscribed !== true) {
        throw new Error(
          `[smoke] E2E account is_subscribed=${data.is_subscribed}. ` +
            `Expected steady-state — the deploy pipeline's journey should leave a live subscription. ` +
            `If this fails repeatedly, the last E2EGate run may have failed mid-flight; rerun the deploy.`,
        );
      }
    });

    // Covers the ~3-5 min window after a deploy where the new ECS task is still rolling.
    await test.step('Container gateway_healthy', async () => {
      await waitForRunning(API_URL, getToken, 2 * 60_000);
    });
  });

  test('Chat: connect, send, receive', async () => {
    test.setTimeout(3 * 60_000);

    await sharedPage.goto(`${BASE_URL}/chat`, { waitUntil: 'domcontentloaded' });

    await sharedPage.getByText('Connected').waitFor({ state: 'visible', timeout: 60_000 });

    // Dismiss the Telegram setup wizard if shown — ProvisioningStepper's
    // onboardingComplete state is in-memory only, so it re-appears on every
    // fresh /chat load until dismissed.
    await dismissChannelSetupIfPresent(sharedPage);

    const input = sharedPage.getByPlaceholder('Ask anything');
    await input.waitFor({ state: 'visible', timeout: 10_000 });
    await input.fill('Say "hello" and nothing else.');
    await sharedPage.getByTestId('send-button').click();

    const assistantMsg = sharedPage.locator('[data-role="assistant"]').last();
    await assistantMsg.waitFor({ state: 'visible', timeout: 90_000 });
    await expect(assistantMsg).not.toBeEmpty();
  });
});
