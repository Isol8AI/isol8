import type { Page } from '@playwright/test';

const TEST_CARD = {
  number: '4242424242424242',
  expiry: '1234',
  cvc: '123',
  name: 'E2E Test',
};

/**
 * Drive the Stripe-hosted Checkout page (`checkout.stripe.com/c/...`).
 *
 * Layout (verified against the PR #309 deploy artifact, 2026-04-20):
 *   - Top: Express Checkout iframes (Pay with Link, Amazon Pay) — ignore.
 *   - Email field is required and NOT pre-filled — backend creates the
 *     Stripe customer without email (separate bug). Fill it with the test
 *     user's address.
 *   - Payment method appears as a list of radios (Card / Cash App / Klarna
 *     / Bank). The card NUMBER/EXPIRY/CVC iframes are NOT rendered until
 *     the "Pay with card" button under the Card listitem is clicked.
 *   - After expansion, fields live in iframes identified by stable `title`
 *     attributes ("Secure card number input frame", etc).
 *   - Submit button: stable `data-testid="hosted-payment-submit-button"`.
 */
export async function completeStripeCheckout(
  page: Page,
  email: string,
): Promise<void> {
  await page.waitForURL(/checkout\.stripe\.com/, { timeout: 30_000 });
  await page.waitForLoadState('domcontentloaded');

  // Email — required for new customers. Backend doesn't pre-fill (bug to
  // fix separately). Fill it so Stripe can move on.
  await page.getByRole('textbox', { name: /email/i }).fill(email);

  // Select the Card payment method. The card iframes only render once
  // Card is selected (verified from PR #314 deploy artifact 2026-04-20).
  //
  // Stripe styles the radios as visually-hidden inputs with a custom
  // div wrapper that handles the click — playwright's .check() rejects
  // because the underlying <input type="radio"> isn't visible/actionable
  // and the call hangs to per-test timeout. Click the listitem (the
  // wrapper Stripe wires the click handler onto) instead.
  // Verified from PR #318 deploy artifact (2026-04-20).
  await page
    .getByRole('listitem')
    .filter({ has: page.getByRole('radio', { name: 'Card' }) })
    .click();

  const numberFrame = page.frameLocator('iframe[title="Secure card number input frame"]');
  const expiryFrame = page.frameLocator('iframe[title="Secure expiration date input frame"]');
  const cvcFrame = page.frameLocator('iframe[title="Secure CVC input frame"]');

  // Wait for the card number iframe to actually exist before filling.
  await numberFrame.locator('[name="cardnumber"]').waitFor({ state: 'visible', timeout: 30_000 });
  await numberFrame.locator('[name="cardnumber"]').fill(TEST_CARD.number);
  await expiryFrame.locator('[name="exp-date"]').fill(TEST_CARD.expiry);
  await cvcFrame.locator('[name="cvc"]').fill(TEST_CARD.cvc);

  const nameInput = page.locator('input[name="billingName"]');
  if (await nameInput.isVisible({ timeout: 1_000 }).catch(() => false)) {
    await nameInput.fill(TEST_CARD.name);
  }

  await page.getByTestId('hosted-payment-submit-button').click();
  await page.waitForURL(/\/chat\?subscription=success/, { timeout: 60_000 });
}
