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
 * Retrieve the backend's Stripe customer ID.
 *
 * The backend creates Stripe customers with metadata.owner_id but NO email,
 * so we can't find them via customers.list({ email }). Instead, we use
 * Stripe's Search API to find customers by owner_id metadata.
 *
 * Calls GET /billing/account first to ensure the billing account + Stripe
 * customer exist.
 */
export async function getBackendStripeCustomerId(
  clerkUserId: string,
  apiUrl: string,
  getToken: () => Promise<string>,
): Promise<string> {
  // Ensure the billing account exists (creates Stripe customer if needed)
  const token = await getToken();
  const res = await fetch(`${apiUrl}/billing/account`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(`GET /billing/account failed: ${res.status}`);

  // Search for the backend-created customer by owner_id metadata
  const result = await stripe().customers.search({
    query: `metadata["owner_id"]:"${clerkUserId}"`,
  });
  if (result.data.length === 0) {
    throw new Error(`No Stripe customer found with owner_id=${clerkUserId}`);
  }
  // Use the most recently created one
  return result.data[0].id;
}

/**
 * Create a Stripe subscription on a specific customer.
 * The metadata.plan_tier field is required by the backend webhook handler.
 */
export async function createSubscription(
  customerId: string,
  priceId: string,
): Promise<Stripe.Subscription> {

  // Attach a fresh test payment method and use the returned ID
  const pm = await stripe().paymentMethods.attach('pm_card_visa', { customer: customerId });
  await stripe().customers.update(customerId, {
    invoice_settings: { default_payment_method: pm.id },
  });

  // Create subscription
  const subscription = await stripe().subscriptions.create({
    customer: customerId,
    items: [{ price: priceId }],
    default_payment_method: pm.id,
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
  getToken: () => Promise<string>,
  timeoutMs: number,
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let lastIsSubscribed: unknown = undefined;
  while (Date.now() < deadline) {
    const token = await getToken();
    const res = await fetch(`${apiUrl}/billing/account`, {
      headers: { Authorization: `Bearer ${token}` },
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
