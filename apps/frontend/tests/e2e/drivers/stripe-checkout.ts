import type { Page, Frame } from '@playwright/test';

const TEST_CARD = {
  number: '4242424242424242',
  expiry: '1234',
  cvc: '123',
  name: 'E2E Test',
  zip: '94103',
};

/**
 * Drive the Stripe-hosted Checkout page (`checkout.stripe.com/c/...`).
 *
 * Layout (verified against the PR #320 deploy artifact, 2026-04-20):
 *   - Top: Express Checkout iframes (Pay with Link, Amazon Pay) — ignore.
 *   - Email field is required and NOT pre-filled (backend creates the
 *     Stripe customer with email=null when the Clerk JWT template doesn't
 *     include the `email` claim — separate bug). Fill it.
 *   - Payment method appears as a list of radios (Card / Cash App / Klarna
 *     / Bank). The card form only renders once Card is selected.
 *   - Stripe's card form layout VARIES between accounts/versions:
 *       - Sometimes 3 separate iframes (number/expiry/CVC) titled
 *         "Secure card number input frame", etc.
 *       - Sometimes 1 combined iframe with all three inputs visible.
 *     Driver enumerates frames to find the one hosting `cardnumber` and
 *     fills inside that frame — works for both layouts.
 *   - Cardholder name + ZIP + Country are on the page (not in iframe).
 *   - Submit button: stable `data-testid="hosted-payment-submit-button"`.
 */
export async function completeStripeCheckout(
  page: Page,
  email: string,
): Promise<void> {
  await page.waitForURL(/checkout\.stripe\.com/, { timeout: 30_000 });
  await page.waitForLoadState('domcontentloaded');

  await page.getByRole('textbox', { name: /email/i }).fill(email);

  // Click the Card listitem — Stripe wraps the radio with a custom div
  // that handles the click; the underlying <input> is visually hidden.
  await page
    .getByRole('listitem')
    .filter({ has: page.getByRole('radio', { name: 'Card' }) })
    .click();

  // Find the iframe that hosts the card form by polling all frames for
  // the one that contains the cardnumber input. This handles both the
  // 3-iframe layout and the single combined-card-iframe layout.
  const cardFrame = await findFrameWith(page, '[name="cardnumber"]', 30_000);
  await cardFrame.locator('[name="cardnumber"]').fill(TEST_CARD.number);
  await cardFrame.locator('[name="exp-date"]').fill(TEST_CARD.expiry);
  await cardFrame.locator('[name="cvc"]').fill(TEST_CARD.cvc);
  // Combined-iframe layout puts ZIP inside the card iframe too. Try
  // there first, fall back to the page-level input.
  const zipInFrame = cardFrame.locator('[name="postalCode"]');
  if (await zipInFrame.count().then((n) => n > 0).catch(() => false)) {
    await zipInFrame.fill(TEST_CARD.zip);
  }

  // Cardholder name (page-level on both layouts; sometimes absent).
  const nameInput = page.locator('input[name="billingName"]');
  if (await nameInput.isVisible({ timeout: 1_000 }).catch(() => false)) {
    await nameInput.fill(TEST_CARD.name);
  }

  // ZIP at page level (split-iframe layout has it outside the card iframe).
  const zipPage = page.getByLabel(/zip|postal/i);
  if (await zipPage.isVisible({ timeout: 1_000 }).catch(() => false)) {
    await zipPage.fill(TEST_CARD.zip).catch(() => {});
  }

  await page.getByTestId('hosted-payment-submit-button').click();
  await page.waitForURL(/\/chat\?subscription=success/, { timeout: 60_000 });
}

async function findFrameWith(page: Page, selector: string, timeoutMs: number): Promise<Frame> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    for (const frame of page.frames()) {
      try {
        const count = await frame.locator(selector).count();
        if (count > 0) return frame;
      } catch {
        // Frame may have detached mid-iteration; ignore and continue.
      }
    }
    await page.waitForTimeout(500);
  }
  throw new Error(`findFrameWith: no frame contains "${selector}" after ${timeoutMs}ms`);
}
