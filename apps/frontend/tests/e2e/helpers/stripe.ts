import Stripe from 'stripe';

const POLL_INTERVAL_MS = 5000;

function getStripe(): Stripe {
  const stripeKey = process.env.STRIPE_SECRET_KEY;
  if (!stripeKey) throw new Error('STRIPE_SECRET_KEY env var is required');
  return new Stripe(stripeKey, {
    apiVersion: '2025-01-27.acacia' as Parameters<typeof Stripe>[1]['apiVersion'],
  });
}

let _stripe: Stripe | undefined;
function stripe(): Stripe {
  if (!_stripe) _stripe = getStripe();
  return _stripe;
}

/**
 * Cancel any active/trialing/incomplete subscriptions for a given email.
 * Safe to call when no subscription exists (no-op).
 */
export async function cancelSubscriptionIfExists(email: string): Promise<void> {
  const customers = await stripe().customers.list({ email, limit: 100 });
  for (const customer of customers.data) {
    const [active, trialing, incomplete] = await Promise.all([
      stripe().subscriptions.list({ customer: customer.id, status: 'active' }),
      stripe().subscriptions.list({ customer: customer.id, status: 'trialing' }),
      stripe().subscriptions.list({ customer: customer.id, status: 'incomplete' }),
    ]);
    const allSubs = [...active.data, ...trialing.data, ...incomplete.data];
    for (const sub of allSubs) {
      await stripe().subscriptions.cancel(sub.id);
    }
  }
}

/**
 * Look up or create a Stripe customer for the email, attach the built-in
 * test card pm_card_visa, and create a subscription for the given price.
 * The metadata.plan_tier field is required by the backend webhook handler.
 */
export async function createSubscription(
  email: string,
  priceId: string,
): Promise<Stripe.Subscription> {
  // Look up or create customer
  const existing = await stripe().customers.list({ email, limit: 1 });
  let customerId: string;
  if (existing.data.length > 0) {
    customerId = existing.data[0].id;
  } else {
    const customer = await stripe().customers.create({ email });
    customerId = customer.id;
  }

  // Attach the built-in test payment method
  await stripe().paymentMethods.attach('pm_card_visa', { customer: customerId });
  await stripe().customers.update(customerId, {
    invoice_settings: { default_payment_method: 'pm_card_visa' },
  });

  // Create subscription
  const subscription = await stripe().subscriptions.create({
    customer: customerId,
    items: [{ price: priceId }],
    default_payment_method: 'pm_card_visa',
    metadata: { plan_tier: 'starter' },
  });

  return subscription;
}

/**
 * Poll GET ${apiUrl}/billing/account until is_subscribed === true.
 * Throws on non-ok responses (except 503 which is swallowed).
 * Throws with descriptive error if timeout is exceeded.
 */
export async function waitForSubscriptionActive(
  apiUrl: string,
  authToken: string,
  timeoutMs: number,
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let lastIsSubscribed: unknown = undefined;
  while (Date.now() < deadline) {
    const res = await fetch(`${apiUrl}/billing/account`, {
      headers: { Authorization: `Bearer ${authToken}` },
    });
    if (res.ok) {
      const data = await res.json();
      lastIsSubscribed = data.is_subscribed;
      if (data.is_subscribed === true) return;
    } else if (res.status !== 503) {
      throw new Error(`waitForSubscriptionActive: unexpected response ${res.status}`);
    }
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
  }
  throw new Error(`waitForSubscriptionActive: timeout after ${timeoutMs}ms (last is_subscribed=${lastIsSubscribed})`);
}
