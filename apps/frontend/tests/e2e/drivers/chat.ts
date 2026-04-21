import { expect, type Page } from '@playwright/test';

export async function waitForChatReady(page: Page): Promise<void> {
  // Ready signal: the send-button is VISIBLE. It may be disabled (empty
  // input, no agent selected, or container provisioning) — that's fine
  // for readiness; sendMessageAndWaitForResponse fills the input first
  // which enables it. What we're checking is that the chat surface has
  // rendered at all.
  //
  // History from PR #342 (run 24721205698): tried "Start a conversation"
  // paragraph as the ready signal — but that only renders on a fresh
  // agent with no history. Step 5 reuses Step 3's chat history so the
  // paragraph is absent; waitForChatReady timed out while the chat
  // surface was in fact fully ready.
  //
  // While polling, also dismiss the channel-onboarding wizard (Set up
  // Telegram / Discord / WhatsApp) if it appears — it auto-opens after
  // the WS reconnects post-upgrade and covers the chat input. And reload
  // the page every 60s if the "Select an agent" empty state is stuck —
  // agents.list sometimes returns empty during container cold-start
  // (PR #340 run 24705367375: empty sidebar + disabled send, click hung
  // 25 min).
  const deadline = Date.now() + 10 * 60_000;
  const sendButton = page.getByTestId('send-button');
  const wizardCancel = page.getByRole('button', { name: 'Cancel' });
  const emptyState = page.getByText('Select an agent', { exact: false });
  let lastRefresh = Date.now();

  while (Date.now() < deadline) {
    if (await sendButton.isVisible({ timeout: 500 }).catch(() => false)) {
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
    'waitForChatReady: send-button never became visible within 10 min ' +
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
  // Click with a short explicit timeout — if actionability fails fast,
  // the test budget won't be consumed by a 25-min retry loop (PR #340
  // run 24704615472: click() hung full test budget on disabled button).
  await page.getByTestId('send-button').click({ timeout: 30_000 });

  // Wait for a strictly-newer assistant message to appear and contain text.
  const timeout = opts.timeoutMs ?? 90_000;
  await expect(assistants).toHaveCount(before + 1, { timeout });
  const newest = assistants.nth(before);
  await newest.waitFor({ state: 'visible', timeout });
  await expect(newest).not.toBeEmpty();
}
