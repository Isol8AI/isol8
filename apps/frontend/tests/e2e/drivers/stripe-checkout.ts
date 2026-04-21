import type { Page, Frame, Locator } from '@playwright/test';

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
 * Layouts seen in this account (verified from PR #321 deploy artifact,
 * 2026-04-21):
 *   - Email field is required and NOT pre-filled (backend creates the
 *     Stripe customer with email=null when the Clerk JWT template doesn't
 *     include the `email` claim — separate bug). Fill it.
 *   - Payment method radio list (Card / Cash App / Klarna / Bank). Card
 *     is checked by default and its form is already expanded.
 *   - Card form layout VARIES across accounts/versions:
 *       (a) Native on-page inputs — `getByRole('textbox', name: 'Card number')`,
 *           etc. No iframe. Seen on this dev account.
 *       (b) Single combined iframe with all three inputs.
 *       (c) Three separate iframes (number / exp / CVC).
 *     Driver tries native (a) first, falls back to iframe (b/c).
 *   - Submit button: stable `data-testid="hosted-payment-submit-button"`.
 */
export async function completeStripeCheckout(
  page: Page,
  email: string,
): Promise<void> {
  await page.waitForURL(/checkout\.stripe\.com/, { timeout: 30_000 });
  await page.waitForLoadState('domcontentloaded');

  await page.getByRole('textbox', { name: /email/i }).fill(email);

  // Select the Card payment method if not already selected. The radio is
  // visually hidden — click the listitem wrapper which is what handles
  // the click. If Card is already checked + form expanded, this is a no-op.
  const cardListItem = page
    .getByRole('listitem')
    .filter({ has: page.getByRole('radio', { name: 'Card' }) });
  if (await cardListItem.count().then((n) => n > 0).catch(() => false)) {
    await cardListItem.click().catch(() => {
      // Already selected, or click target moved — proceed.
    });
  }

  // Try native on-page inputs first (layout a). 5s probe — if they
  // appear, fill and skip iframe path entirely.
  const pageCardNumber = page.getByRole('textbox', { name: 'Card number' });
  if (await pageCardNumber.isVisible({ timeout: 5_000 }).catch(() => false)) {
    await pageCardNumber.fill(TEST_CARD.number);
    await page.getByRole('textbox', { name: /^Expiration/i }).fill(TEST_CARD.expiry);
    await page.getByRole('textbox', { name: 'CVC' }).fill(TEST_CARD.cvc);
  } else {
    // Layouts b/c: card inputs live inside an iframe. Enumerate frames.
    const cardFrame = await findFrameWith(page, '[name="cardnumber"]', 30_000);
    await cardFrame.locator('[name="cardnumber"]').fill(TEST_CARD.number);
    await cardFrame.locator('[name="exp-date"]').fill(TEST_CARD.expiry);
    await cardFrame.locator('[name="cvc"]').fill(TEST_CARD.cvc);
    const zipInFrame = cardFrame.locator('[name="postalCode"]');
    if (await zipInFrame.count().then((n) => n > 0).catch(() => false)) {
      await zipInFrame.fill(TEST_CARD.zip);
    }
  }

  // Cardholder name + ZIP are always page-level (when present).
  await fillIfVisible(page.getByRole('textbox', { name: 'Cardholder name' }), TEST_CARD.name);
  await fillIfVisible(page.getByRole('textbox', { name: 'ZIP' }), TEST_CARD.zip);

  // Uncheck "Save my information for faster checkout" — it's checked by
  // default and enrolls the customer in Stripe Link, which makes Phone
  // number a required field. Test card has no phone; submit gets rejected
  // with a red border on Phone (verified from PR #334 e2e-dev artifact).
  const linkOptIn = page.getByRole('checkbox', {
    name: /save my information for faster checkout/i,
  });
  if (await linkOptIn.isChecked({ timeout: 2_000 }).catch(() => false)) {
    await linkOptIn.uncheck();
  }

  await page.getByTestId('hosted-payment-submit-button').click();
  await page.waitForURL(/\/chat\?subscription=success/, { timeout: 60_000 });
}

async function fillIfVisible(locator: Locator, value: string): Promise<void> {
  if (await locator.isVisible({ timeout: 1_000 }).catch(() => false)) {
    await locator.fill(value).catch(() => {});
  }
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
