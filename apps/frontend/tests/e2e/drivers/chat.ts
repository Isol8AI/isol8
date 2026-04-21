import { expect, type Page } from '@playwright/test';

export async function waitForChatReady(page: Page): Promise<void> {
  // Poll for the send-button up to 10 min. While polling, dismiss any
  // channel-onboarding wizard that appears (Set up Telegram / Discord /
  // WhatsApp) — it auto-opens AFTER the WS reconnects post-upgrade, and
  // it covers the chat input so send-button never renders.
  //
  // Why a loop instead of a one-shot probe: the wizard appears
  // asynchronously after the page settles (verified from PR #339 e2e-dev
  // artifact — at 10-min timeout, screenshot still showed the wizard
  // covering the surface, meaning a single check at the start of
  // waitForChatReady fires before the wizard is on-screen).
  //
  // Why we still need to handle the send-button being slow on free tier:
  // the free-tier container can scale to zero in the gap between
  // containerHealthy returning (status:running) and the frontend gateway-WS
  // handshake completing — page rebounds to "Container provisioning —
  // waiting for ECS task" and send-button disappears. The same loop covers
  // that case (Codex re-flag from PR #314 deploy 2026-04-20).
  const deadline = Date.now() + 10 * 60_000;
  const sendButton = page.getByTestId('send-button');
  const wizardCancel = page.getByRole('button', { name: 'Cancel' });
  const emptyState = page.getByText('Select an agent', { exact: false });
  let lastRefresh = Date.now();

  while (Date.now() < deadline) {
    // Ready: send-button visible AND enabled. Playwright's click waits
    // for actionability, but we've seen it hang 25 min on a disabled
    // send-button (no agent selected because agents.list returned empty).
    if (
      (await sendButton.isVisible({ timeout: 500 }).catch(() => false)) &&
      (await sendButton.isEnabled({ timeout: 500 }).catch(() => false))
    ) {
      return;
    }

    // Dismiss the channel-onboarding wizard if it's up — it covers the
    // chat input so send-button never renders.
    if (await wizardCancel.isVisible({ timeout: 500 }).catch(() => false)) {
      await wizardCancel.click().catch(() => {});
      continue;
    }

    // "Select an agent" empty state = agents.list returned empty even
    // though the container is healthy. Refresh the page every 60s to
    // re-run agents.list; if a stale cached result is the issue, a fresh
    // fetch will pick up the newly-created agent. Verified from PR #340
    // e2e-dev artifact (run 24705367375) — personal Step 3 screenshot
    // showed empty sidebar + disabled send.
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
    'waitForChatReady: send-button never enabled within 10 min ' +
      '(wizard persisting, empty agent list, or container stuck provisioning)',
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
  await page.getByTestId('send-button').click();

  // Wait for a strictly-newer assistant message to appear and contain text.
  const timeout = opts.timeoutMs ?? 90_000;
  await expect(assistants).toHaveCount(before + 1, { timeout });
  const newest = assistants.nth(before);
  await newest.waitFor({ state: 'visible', timeout });
  await expect(newest).not.toBeEmpty();
}
