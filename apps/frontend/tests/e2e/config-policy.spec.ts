/**
 * Config policy enforcement E2E.
 *
 * These tests verify the config reconciler behaviour end-to-end:
 *  1. Agent edits to NON-locked fields (e.g. cron) persist past one reconciler tick.
 *  2. Agent attempts to change a LOCKED field (primary model) get reverted within
 *     one reconciler tick window (~1–2s).
 *
 * Requirements to run:
 *   - Backend deployment must have `CONFIG_RECONCILER_MODE=enforce`.
 *   - The dev Clerk instance + test user must be reachable (same flow as
 *     journey.spec.ts).
 *   - WebSocket agent chat must be working against the target deployment
 *     (journey.spec.ts currently skips chat due to a WS 500 during handshake).
 *
 * These tests are SKIPPED by default. To run them against a suitable staging
 * deployment, set `E2E_CONFIG_POLICY=1` in the environment:
 *
 *   E2E_CONFIG_POLICY=1 pnpm run test:e2e config-policy.spec.ts
 *
 * They share the `isol8-e2e-testing@mailsac.com` Clerk account with the journey
 * gate; do NOT run them in parallel with that gate (they rely on the same
 * container being provisioned + subscribed, and the journey gate cancels its
 * subscription on tear-down).
 */

import { test, expect, type Page } from '@playwright/test';
import { clerkSetup } from '@clerk/testing/playwright';
import { waitForRunning } from './helpers/provision';

const E2E_EMAIL = 'isol8-e2e-testing@mailsac.com';
const BASE_URL = process.env.BASE_URL ?? 'http://localhost:3000';
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000/api/v1';

// Gate these tests behind an explicit opt-in env var. They need
// CONFIG_RECONCILER_MODE=enforce on the backend + agent-chat working; neither
// is guaranteed by the default E2E gate, so running them unconditionally would
// produce flakes / false failures.
const ENABLED = process.env.E2E_CONFIG_POLICY === '1';

async function createSignInToken(): Promise<{ ticket: string; userId: string }> {
  const secretKey = process.env.CLERK_SECRET_KEY;
  if (!secretKey) throw new Error('[e2e] CLERK_SECRET_KEY not set');

  const usersRes = await fetch(
    `https://api.clerk.com/v1/users?email_address[]=${encodeURIComponent(E2E_EMAIL)}`,
    { headers: { Authorization: `Bearer ${secretKey}` } },
  );
  if (!usersRes.ok) throw new Error(`[e2e] Users API ${usersRes.status}: ${await usersRes.text()}`);
  const users = (await usersRes.json()) as Array<{ id: string }>;
  if (!users.length) throw new Error(`[e2e] No user found for ${E2E_EMAIL}`);

  const tokenRes = await fetch('https://api.clerk.com/v1/sign_in_tokens', {
    method: 'POST',
    headers: { Authorization: `Bearer ${secretKey}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id: users[0].id }),
  });
  if (!tokenRes.ok) {
    throw new Error(`[e2e] Sign-in token API ${tokenRes.status}: ${await tokenRes.text()}`);
  }
  const { token } = (await tokenRes.json()) as { token: string };
  return { ticket: token, userId: users[0].id };
}

/**
 * Sign in the shared E2E test user via a Clerk backend-issued ticket (no
 * password/MFA). Mirrors the flow in journey.spec.ts; kept as a local helper
 * here instead of exported because the ticket + setActive sequence is tied to
 * this test's `page` lifecycle.
 */
async function signInE2EUser(page: Page): Promise<void> {
  await clerkSetup();
  await page.goto(BASE_URL, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(
    () => {
      const w = window as Window & { Clerk?: { loaded?: boolean; client?: unknown } };
      return w.Clerk?.loaded === true && w.Clerk?.client != null;
    },
    { timeout: 30_000 },
  );

  const { ticket } = await createSignInToken();
  await page.evaluate(async (t: string) => {
    const w = window as unknown as {
      Clerk: {
        client: { signIn: { create: (opts: Record<string, string>) => Promise<{ createdSessionId: string }> } };
        setActive: (opts: { session: string }) => Promise<void>;
      };
    };
    const si = await w.Clerk.client.signIn.create({ strategy: 'ticket', ticket: t });
    await w.Clerk.setActive({ session: si.createdSessionId });
  }, ticket);

  const sid = await page.evaluate(() => {
    const w = window as unknown as { Clerk?: { session?: { id?: string } } };
    return w.Clerk?.session?.id ?? null;
  });
  if (!sid) throw new Error('[e2e] No session after sign-in token');
}

async function getTokenFrom(page: Page): Promise<string> {
  return page.evaluate(async () => {
    const w = window as Window & { Clerk?: { session?: { getToken: () => Promise<string> } } };
    return (await w.Clerk?.session?.getToken()) ?? '';
  });
}

/**
 * Read the caller's current openclaw.json config via the same RPC the UI uses.
 * Returns the parsed config object.
 */
async function readConfig(page: Page): Promise<Record<string, unknown>> {
  const token = await getTokenFrom(page);
  // /container/rpc proxies RPC to the user's OpenClaw gateway. `config.read`
  // is the canonical read path used by the ConfigPanel.
  const res = await fetch(`${API_URL}/container/rpc`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ method: 'config.read', params: {} }),
  });
  if (!res.ok) throw new Error(`config.read failed: ${res.status} ${await res.text()}`);
  const data = (await res.json()) as { result?: Record<string, unknown> };
  return data.result ?? {};
}

async function sendChatMessage(page: Page, text: string): Promise<void> {
  const input = page.getByPlaceholder('Ask anything');
  await expect(input).toBeVisible({ timeout: 30_000 });
  await input.fill(text);
  await page.getByTestId('send-button').click();
}

async function waitForAssistantResponse(page: Page, timeoutMs = 90_000): Promise<void> {
  // Send-button swaps to stop-button while streaming; wait for it to swap back.
  await expect(page.getByTestId('stop-button')).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('send-button')).toBeVisible({ timeout: timeoutMs });
}

test.describe('Config policy enforcement', () => {
  test.describe.configure({ mode: 'serial' });

  test.skip(!ENABLED, 'Requires CONFIG_RECONCILER_MODE=enforce + WS chat. Set E2E_CONFIG_POLICY=1 to run.');

  let sharedPage: Page;
  let originalConfig: Record<string, unknown> = {};

  test.beforeAll(async ({ browser }) => {
    test.setTimeout(5 * 60_000);
    const ctx = await browser.newContext({
      extraHTTPHeaders: process.env.VERCEL_AUTOMATION_BYPASS_SECRET
        ? { 'x-vercel-protection-bypass': process.env.VERCEL_AUTOMATION_BYPASS_SECRET }
        : {},
    });
    sharedPage = await ctx.newPage();
    await signInE2EUser(sharedPage);

    // Make sure the container is provisioned + healthy. The journey gate
    // normally leaves one running; if not, POST /debug/provision is idempotent.
    const token = await getTokenFrom(sharedPage);
    const provisionRes = await fetch(`${API_URL}/debug/provision`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    });
    if (provisionRes.status !== 200 && provisionRes.status !== 409) {
      throw new Error(`[e2e] Provision failed: ${provisionRes.status}`);
    }
    await waitForRunning(API_URL, () => getTokenFrom(sharedPage), 5 * 60_000);

    // Snapshot the config so we can restore it after the tests — the "agent
    // changes X" scenarios mutate shared state on EFS.
    originalConfig = await readConfig(sharedPage);

    await sharedPage.goto(`${BASE_URL}/chat`, { waitUntil: 'domcontentloaded' });
  });

  test.afterAll(async () => {
    // Best-effort restore: use the admin PATCH endpoint to put the config
    // back the way we found it. We don't fail the suite if this errors —
    // the reconciler would correct any locked-field drift on the next tick
    // anyway, and the journey gate's own cleanup restores the rest.
    try {
      if (sharedPage && Object.keys(originalConfig).length > 0) {
        const token = await getTokenFrom(sharedPage);
        await fetch(`${API_URL}/config`, {
          method: 'PATCH',
          headers: {
            Authorization: `Bearer ${token}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ patch: originalConfig }),
        });
      }
    } catch (err) {
      console.error('[e2e] afterAll config restore failed (non-fatal):', err);
    }
    await sharedPage?.context().close();
  });

  test('agent edits to non-locked fields persist past reconciler tick', async () => {
    test.setTimeout(3 * 60_000);

    // Ask the agent to add a cron job. `crons` is not a locked field — the
    // policy allows users on any tier to define their own schedules.
    await sendChatMessage(
      sharedPage,
      'Add a cron job with id "e2e-cron-test" that runs daily at 9am (schedule "0 9 * * *") ' +
        'and triggers a noop. Confirm the exact id you used.',
    );
    await waitForAssistantResponse(sharedPage);

    // Wait well past the 1s reconciler tick interval so any revert would have
    // fired by now.
    await sharedPage.waitForTimeout(3_000);

    // Non-locked changes must survive. Assert via the RPC snapshot (more
    // reliable than chasing a potentially virtualised config panel).
    const config = await readConfig(sharedPage);
    const crons = (config.crons ?? {}) as Record<string, unknown>;
    expect(
      Object.keys(crons),
      'non-locked cron entry should persist past reconciler tick',
    ).toContain('e2e-cron-test');
  });

  test('agent attempt to switch primary model gets reverted', async () => {
    test.setTimeout(3 * 60_000);

    // Ask the agent to switch its primary model. For the starter tier the
    // policy pins primary to Qwen3 VL 235B — any other value is drift and
    // must be reverted within one reconciler tick.
    await sendChatMessage(
      sharedPage,
      'Switch your primary model to amazon-bedrock/minimax.minimax-m2.5 in the ' +
        'agent defaults and confirm when done.',
    );
    await waitForAssistantResponse(sharedPage);

    // Give the reconciler two ticks of headroom (default interval is 1s).
    await sharedPage.waitForTimeout(3_000);

    const config = await readConfig(sharedPage);
    const primary = (((config.agents as Record<string, unknown> | undefined)
      ?.defaults as Record<string, unknown> | undefined)
      ?.model as Record<string, unknown> | undefined)?.primary;

    // Whatever the agent wrote, the reconciler must have restored the
    // tier-allowed primary. We assert it's NOT the minimax value the agent
    // tried to set — a strict equality check to the starter-tier primary
    // would couple this test to the exact model id, which may evolve.
    expect(
      primary,
      'reconciler must revert agent-attempted primary-model change',
    ).not.toBe('amazon-bedrock/minimax.minimax-m2.5');
  });
});
