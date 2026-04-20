import Stripe from 'stripe';

let _client: Stripe | undefined;
function client(secretKey: string): Stripe {
  if (!_client) {
    _client = new Stripe(secretKey, {
      apiVersion: '2025-01-27.acacia' as Parameters<typeof Stripe>[1]['apiVersion'],
    });
  }
  return _client;
}

export async function findCustomerByEmail(
  secretKey: string,
  email: string,
): Promise<Stripe.Customer | null> {
  const list = await client(secretKey).customers.list({ email, limit: 100 });
  return list.data[0] ?? null;
}

export async function setCustomerMetadata(
  secretKey: string,
  customerId: string,
  metadata: Record<string, string>,
): Promise<void> {
  await client(secretKey).customers.update(customerId, { metadata });
}

export async function cancelSubsAndDeleteCustomer(
  secretKey: string,
  email: string,
): Promise<void> {
  const customers = await client(secretKey).customers.list({ email, limit: 100 });
  for (const customer of customers.data) {
    const subs = await client(secretKey).subscriptions.list({
      customer: customer.id,
      status: 'all',
      limit: 100,
    });
    for (const sub of subs.data) {
      if (sub.status === 'canceled' || sub.status === 'incomplete_expired') continue;
      try {
        await client(secretKey).subscriptions.cancel(sub.id);
      } catch (err) {
        console.error(`[e2e] cancel sub ${sub.id} failed:`, err);
      }
    }
    try {
      await client(secretKey).customers.del(customer.id);
    } catch (err) {
      console.error(`[e2e] delete customer ${customer.id} failed:`, err);
    }
  }
}
