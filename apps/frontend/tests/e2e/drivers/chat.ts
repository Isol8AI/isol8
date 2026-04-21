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

  while (Date.now() < deadline) {
    if (await sendButton.isVisible({ timeout: 500 }).catch(() => false)) {
      return;
    }
    if (await wizardCancel.isVisible({ timeout: 500 }).catch(() => false)) {
      await wizardCancel.click().catch(() => {});
      // Loop again — wizard may have multiple steps or there may be a
      // follow-up wizard for another channel.
      continue;
    }
    await page.waitForTimeout(1_000);
  }
  throw new Error(
    'waitForChatReady: send-button never appeared within 10 min ' +
      '(wizard may keep reappearing or container is stuck provisioning)',
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
