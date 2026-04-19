import { expect, type Page } from '@playwright/test';

export async function waitForChatReady(page: Page): Promise<void> {
  await page.getByText('Connected').waitFor({ state: 'visible', timeout: 60_000 });
  await page
    .getByPlaceholder('Ask anything')
    .waitFor({ state: 'visible', timeout: 30_000 });
}

export async function sendMessageAndWaitForResponse(
  page: Page,
  message: string,
  opts: { timeoutMs?: number } = {},
): Promise<void> {
  const input = page.getByPlaceholder('Ask anything');
  await input.fill(message);
  await page.getByTestId('send-button').click();

  const assistantMsg = page.locator('[data-role="assistant"]').last();
  await assistantMsg.waitFor({ state: 'visible', timeout: opts.timeoutMs ?? 90_000 });
  await expect(assistantMsg).not.toBeEmpty();
}
