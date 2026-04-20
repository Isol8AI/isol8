import type { AuthedFetch } from '../fixtures/api';

export async function billingTier(
  api: AuthedFetch,
  expected: 'free' | 'starter' | 'pro' | 'enterprise',
  opts: { timeoutMs?: number } = {},
): Promise<void> {
  const deadline = Date.now() + (opts.timeoutMs ?? 120_000);
  let last: string | undefined;
  while (Date.now() < deadline) {
    const data = await api.get<{ tier: string }>('/billing/account');
    last = data.tier;
    if (last === expected) return;
    await new Promise((r) => setTimeout(r, 3000));
  }
  throw new Error(`billingTier: expected ${expected}, last seen ${last}`);
}

export async function isSubscribed(
  api: AuthedFetch,
  expected: boolean,
  opts: { timeoutMs?: number } = {},
): Promise<void> {
  const deadline = Date.now() + (opts.timeoutMs ?? 120_000);
  let last: boolean | undefined;
  while (Date.now() < deadline) {
    const data = await api.get<{ is_subscribed: boolean }>('/billing/account');
    last = data.is_subscribed;
    if (last === expected) return;
    await new Promise((r) => setTimeout(r, 3000));
  }
  throw new Error(`isSubscribed: expected ${expected}, last seen ${last}`);
}
