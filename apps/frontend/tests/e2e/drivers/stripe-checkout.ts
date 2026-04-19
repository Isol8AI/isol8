import type { Page } from '@playwright/test';

const TEST_CARD = {
  // Stripe test card — always succeeds in test mode.
  number: '4242424242424242',
  expiry: '1234', // MMYY, no separator (Stripe formats it)
  cvc: '123',
  name: 'E2E Test',
};

/**
 * Drive the Stripe-hosted Checkout page (`checkout.stripe.com/c/...`).
 *
 * Layout we're driving:
 *   - The `email` field is NOT filled here. The backend creates a Stripe
 *     customer with the user's email *before* opening Checkout (see
 *     `billing_service.create_checkout_session`), so Checkout is opened in
 *     `customer=...` mode and the email is pre-attached.
 *   - Card number / expiry / CVC each live inside their own iframe. Stripe
 *     sets a stable `title` attribute on these iframes that survives their
 *     UI revs better than the auto-generated `name=__privateStripeFrame…`
 *     attribute, so we locate by title.
 *   - Cardholder name and country/postal sometimes show, sometimes don't,
 *     depending on the Checkout config and detected geolocation. Both are
 *     treated as optional.
 *   - Submit button has a stable `data-testid="hosted-payment-submit-button"`.
 */
export async function completeStripeCheckout(page: Page): Promise<void> {
  await page.waitForURL(/checkout\.stripe\.com/, { timeout: 30_000 });
  await page.waitForLoadState('domcontentloaded');

  const numberFrame = page.frameLocator('iframe[title="Secure card number input frame"]');
  const expiryFrame = page.frameLocator('iframe[title="Secure expiration date input frame"]');
  const cvcFrame = page.frameLocator('iframe[title="Secure CVC input frame"]');

  await numberFrame.locator('[name="cardnumber"]').fill(TEST_CARD.number);
  await expiryFrame.locator('[name="exp-date"]').fill(TEST_CARD.expiry);
  await cvcFrame.locator('[name="cvc"]').fill(TEST_CARD.cvc);

  // Cardholder name — present on most Checkout configs but not all. Tolerate.
  const nameInput = page.locator('input[name="billingName"]');
  if (await nameInput.isVisible({ timeout: 1_000 }).catch(() => false)) {
    await nameInput.fill(TEST_CARD.name);
  }

  await page.getByTestId('hosted-payment-submit-button').click();

  // Stripe redirects back to our success_url on success. Allow a generous
  // window for the network round-trip (Stripe → 3DS-skip in test mode →
  // success_url → Vercel → us).
  await page.waitForURL(/\/chat\?subscription=success/, { timeout: 60_000 });
}
