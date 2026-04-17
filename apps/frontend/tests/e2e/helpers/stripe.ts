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
  if (customers.data.length === 0) return; // no customer → nothing to cancel
  for (const customer of customers.data) {
    // `status: 'all'` returns subscriptions in every state (active, trialing,
    // incomplete, past_due, paused, etc.) except already-canceled ones.
    const subs = await stripe().subscriptions.list({ customer: customer.id, status: 'all', limit: 100 });
    for (const sub of subs.data) {
      if (sub.status === 'canceled' || sub.status === 'incomplete_expired') continue;
      try {
        await stripe().subscriptions.cancel(sub.id);
      } catch (err) {
        // Don't let one bad subscription block cleanup of the others.
        console.error(`[e2e] Failed to cancel subscription ${sub.id} (status=${sub.status}):`, err);
      }
    }
  }
}

/**
 * Ensure a billing account + Stripe customer exist for this user by calling
 * POST /billing/checkout on the backend. This creates the DynamoDB billing
 * account row AND Stripe customer (same as clicking "Subscribe" in the UI).
 * We then look up the Stripe customer ID from the backend-created customer.
 *
 * Returns the Stripe customer ID.
 */
export async function ensureBillingCustomer(
  apiUrl: string,
  getToken: () => Promise<string>,
  clerkUserId: string,
): Promise<string> {
  // Call POST /billing/checkout to trigger customer creation on the backend.
  // We don't need to follow the returned checkout_url — we just want the
  // side effect of creating the Stripe customer + DynamoDB billing row.
  const token = await getToken();
  const res = await fetch(`${apiUrl}/billing/checkout`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ tier: 'starter' }),
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`POST /billing/checkout failed: ${res.status} — ${body}`);
  }
  console.log('[e2e] POST /billing/checkout succeeded (customer + billing row created)');

  // The backend just created a Stripe customer with metadata.owner_id.
  // Stripe List API (not Search) returns it immediately — no indexing delay.
  const customers = await stripe().customers.list({ limit: 100 });
  const match = customers.data.find((c) => c.metadata?.owner_id === clerkUserId);
  if (match) {
    console.log(`[e2e] Found Stripe customer via list: ${match.id}`);
    return match.id;
  }

  // Fallback: search (may have indexing delay but customer was just created)
  const result = await stripe().customers.search({
    query: `metadata["owner_id"]:"${clerkUserId}"`,
  });
  if (result.data.length > 0) {
    console.log(`[e2e] Found Stripe customer via search: ${result.data[0].id}`);
    return result.data[0].id;
  }

  throw new Error(`No Stripe customer found for owner_id=${clerkUserId} after checkout`);
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
