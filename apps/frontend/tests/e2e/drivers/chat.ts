import { expect, type Page } from '@playwright/test';

export async function waitForChatReady(page: Page): Promise<void> {
  // Two readiness signals:
  //   1. "Connected" — API WebSocket up (frontend ↔ backend)
  //   2. "Ask anything" placeholder — per-agent gateway WS handshake done
  // The agent gateway can take 1-3 min on a freshly-provisioned container
  // because the OpenClaw process boots, opens its WS, the backend pool
  // attaches, then the frontend reconnects through it.
  await page.getByText('Connected').waitFor({ state: 'visible', timeout: 60_000 });
  // The chat input's placeholder rotates ("Ask anything", suggested bootstrap
  // text, etc.) so don't pin to placeholder text. Wait for the Send button to
  // be present + the textbox to be enabled.
  await page
    .getByTestId('send-button')
    .waitFor({ state: 'visible', timeout: 5 * 60_000 });
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
