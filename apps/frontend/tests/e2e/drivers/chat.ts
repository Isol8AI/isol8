import { expect, type Page } from '@playwright/test';

export async function waitForChatReady(page: Page): Promise<void> {
  // The free-tier container can scale to zero in the gap between
  // containerHealthy returning (status:running) and the frontend gateway-WS
  // handshake completing (the user is "idle" from scale-to-zero's
  // perspective during this window). When that happens the page rebounds
  // to "Container provisioning — waiting for ECS task" and the send-button
  // disappears. We wait for the long-budget ECS-cold-start path: as long
  // as either provisioning or the gateway WS handshake is making progress
  // within the 10-minute outer budget, we keep waiting (Codex re-flag from
  // PR #314 deploy 2026-04-20).
  await page.getByTestId('send-button').waitFor({
    state: 'visible',
    timeout: 10 * 60_000,
  });
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
