import type { Page } from '@playwright/test';

const TEST_CARD = {
  number: '4242 4242 4242 4242',
  expiry: '12 / 34',
  cvc: '123',
  name: 'E2E Test',
};

export async function completeStripeCheckout(page: Page): Promise<void> {
  await page.waitForURL(/checkout\.stripe\.com/, { timeout: 15_000 });

  await page.locator('input[autocomplete="cc-number"]').fill(TEST_CARD.number);
  await page.locator('input[autocomplete="cc-exp"]').fill(TEST_CARD.expiry);
  await page.locator('input[autocomplete="cc-csc"]').fill(TEST_CARD.cvc);
  await page
    .locator('input[name="billingName"]')
    .fill(TEST_CARD.name)
    .catch(() => {});

  await page
    .locator('button[type="submit"]')
    .filter({ hasText: /subscribe|pay|start/i })
    .first()
    .click();

  await page.waitForURL(/\/chat\?subscription=success/, { timeout: 30_000 });
}
