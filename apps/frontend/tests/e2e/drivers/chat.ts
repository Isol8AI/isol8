import { expect, type Page } from '@playwright/test';

export async function waitForChatReady(page: Page): Promise<void> {
  // Ready signal: the "Start a conversation with your agent" paragraph is
  // visible. That paragraph only renders when an agent is selected and
  // loaded — so it differentiates "agent loaded, input empty (send
  // disabled — normal)" from "no agent selected, send disabled (broken
  // state)". Previous attempts waited for the send-button to be
  // visible+enabled, which fails on the legitimate "empty input" state
  // (verified from PR #341 e2e-dev artifact run 24714987157 — send-button
  // was correctly disabled because the textbox had no user text yet; the
  // agent was fully loaded).
  //
  // While polling, also dismiss the channel-onboarding wizard (Set up
  // Telegram / Discord / WhatsApp) if it appears — it auto-opens after
  // the WS reconnects post-upgrade and covers the chat input. And reload
  // the page every 60s if the "Select an agent" empty state is stuck —
  // agents.list sometimes returns empty during the container cold-start
  // race (verified from PR #340 artifact run 24705367375 — personal Step
  // 3 showed empty sidebar + disabled send, click hung 25 min).
  const deadline = Date.now() + 10 * 60_000;
  const readyHeading = page.getByText('Start a conversation with', {
    exact: false,
  });
  const wizardCancel = page.getByRole('button', { name: 'Cancel' });
  const emptyState = page.getByText('Select an agent', { exact: false });
  let lastRefresh = Date.now();

  while (Date.now() < deadline) {
    if (await readyHeading.isVisible({ timeout: 500 }).catch(() => false)) {
      return;
    }
    if (await wizardCancel.isVisible({ timeout: 500 }).catch(() => false)) {
      await wizardCancel.click().catch(() => {});
      continue;
    }
    if (
      (await emptyState.isVisible({ timeout: 500 }).catch(() => false)) &&
      Date.now() - lastRefresh > 60_000
    ) {
      await page.reload().catch(() => {});
      lastRefresh = Date.now();
      continue;
    }
    await page.waitForTimeout(1_000);
  }
  throw new Error(
    'waitForChatReady: chat-ready signal ("Start a conversation") never ' +
      'appeared within 10 min (wizard persisting, empty agent list, or ' +
      'container stuck provisioning)',
  );
}

async function fillChatInput(page: Page, message: string): Promise<void> {
  // Same reason — the textbox has no stable accessible name; locate by role
  // within the chat input region (the only enabled textbox on the page).
  const input = page.getByRole('textbox').last();
  await input.fill(message);
}

export async function sendMessageAndWaitForResponse(
  page: Page,
  message: string,
  opts: { timeoutMs?: number } = {},
): Promise<void> {
  // Snapshot the existing assistant-message count BEFORE sending. Without
  // this, a Step 5 call right after Step 3 would see Step 3's reply still
  // visible and pass instantly, never verifying the new message arrived
  // (Codex P1 on PR #309).
  const assistants = page.locator('[data-role="assistant"]');
  const before = await assistants.count();

  await fillChatInput(page, message);
  // Click with a short explicit timeout — if actionability fails fast,
  // the test budget won't be consumed by a 25-min retry loop. Falls back
  // to standard click if the element is actionable.
  await page.getByTestId('send-button').click({ timeout: 30_000 });

  // Wait for a strictly-newer assistant message to appear and contain text.
  const timeout = opts.timeoutMs ?? 90_000;
  await expect(assistants).toHaveCount(before + 1, { timeout });
  const newest = assistants.nth(before);
  await newest.waitFor({ state: 'visible', timeout });
  await expect(newest).not.toBeEmpty();
}
