import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('../../e2e/fixtures/clerk-admin', () => ({
  createUser: vi.fn(),
  deleteUser: vi.fn(),
  deleteOrg: vi.fn(),
  findUserByEmail: vi.fn(),
}));

vi.mock('../../e2e/fixtures/stripe-admin', () => ({
  cancelSubsAndDeleteCustomer: vi.fn(),
  findCustomerByEmail: vi.fn(),
}));

import { cleanupUser, type E2EUser } from '../../e2e/fixtures/user';
import {
  deleteUser,
  deleteOrg,
  findUserByEmail,
} from '../../e2e/fixtures/clerk-admin';
import {
  cancelSubsAndDeleteCustomer,
  findCustomerByEmail,
} from '../../e2e/fixtures/stripe-admin';

const ENV_KEYS = {
  STRIPE_SECRET_KEY: 'sk_test_stripe',
  CLERK_SECRET_KEY: 'sk_test_clerk',
};

function makeUser(overrides: Partial<E2EUser> = {}): E2EUser {
  return {
    runId: '1776572400000-abcdef',
    email: 'isol8-e2e-test@mailsac.com',
    password: 'pw',
    clerkUserId: 'user_abc',
    page: {} as E2EUser['page'],
    api: { delete: vi.fn().mockResolvedValue({ deleted: {} }) } as unknown as E2EUser['api'],
    ddb: {} as E2EUser['ddb'],
    ...overrides,
  };
}

describe('cleanupUser', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    process.env.STRIPE_SECRET_KEY = ENV_KEYS.STRIPE_SECRET_KEY;
    process.env.CLERK_SECRET_KEY = ENV_KEYS.CLERK_SECRET_KEY;
    vi.mocked(cancelSubsAndDeleteCustomer).mockReset().mockResolvedValue();
    vi.mocked(deleteUser).mockReset().mockResolvedValue();
    vi.mocked(deleteOrg).mockReset().mockResolvedValue();
    vi.mocked(findCustomerByEmail).mockReset().mockResolvedValue(null);
    vi.mocked(findUserByEmail).mockReset().mockResolvedValue(null);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('runs Stripe → backend → Clerk → verification in order', async () => {
    const user = makeUser();

    const promise = cleanupUser(user);
    await vi.runAllTimersAsync();
    await promise;

    const stripeOrder = vi.mocked(cancelSubsAndDeleteCustomer).mock.invocationCallOrder[0];
    const backendOrder = vi.mocked(user.api.delete).mock.invocationCallOrder[0];
    const clerkOrder = vi.mocked(deleteUser).mock.invocationCallOrder[0];
    const verifyStripeOrder = vi.mocked(findCustomerByEmail).mock.invocationCallOrder[0];
    const verifyClerkOrder = vi.mocked(findUserByEmail).mock.invocationCallOrder[0];

    expect(stripeOrder).toBeLessThan(backendOrder);
    expect(backendOrder).toBeLessThan(clerkOrder);
    expect(clerkOrder).toBeLessThan(verifyStripeOrder);
    expect(verifyStripeOrder).toBeLessThan(verifyClerkOrder);

    expect(cancelSubsAndDeleteCustomer).toHaveBeenCalledWith(
      ENV_KEYS.STRIPE_SECRET_KEY,
      user.email,
    );
    expect(user.api.delete).toHaveBeenCalledWith('/debug/user-data');
    expect(deleteUser).toHaveBeenCalledWith({
      secretKey: ENV_KEYS.CLERK_SECRET_KEY,
      userId: user.clerkUserId,
    });
    expect(deleteOrg).not.toHaveBeenCalled();
  });

  it('deletes the org before the user when orgId is set', async () => {
    const user = makeUser({ orgId: 'org_abc' });

    const promise = cleanupUser(user);
    await vi.runAllTimersAsync();
    await promise;

    const orgOrder = vi.mocked(deleteOrg).mock.invocationCallOrder[0];
    const userOrder = vi.mocked(deleteUser).mock.invocationCallOrder[0];
    expect(orgOrder).toBeLessThan(userOrder);
    expect(deleteOrg).toHaveBeenCalledWith({
      secretKey: ENV_KEYS.CLERK_SECRET_KEY,
      orgId: 'org_abc',
    });
  });

  it('throws when Stripe customer still exists after teardown', async () => {
    vi.mocked(findCustomerByEmail).mockResolvedValue({
      id: 'cus_leaked',
    } as Awaited<ReturnType<typeof findCustomerByEmail>>);

    const promise = cleanupUser(makeUser());
    const settled = promise.catch((err) => err);
    await vi.runAllTimersAsync();
    const err = await settled;

    expect(err).toBeInstanceOf(Error);
    expect((err as Error).message).toMatch(/Stripe leak.*cus_leaked/);
  });

  it('throws when Clerk user still exists after teardown', async () => {
    vi.mocked(findUserByEmail).mockResolvedValue({
      id: 'user_leaked',
      email_addresses: [{ email_address: 'isol8-e2e-test@mailsac.com' }],
    });

    const promise = cleanupUser(makeUser());
    const settled = promise.catch((err) => err);
    await vi.runAllTimersAsync();
    const err = await settled;

    expect(err).toBeInstanceOf(Error);
    expect((err as Error).message).toMatch(/Clerk leak.*user_leaked/);
  });

  it('treats missing entities as success (idempotent re-run)', async () => {
    const user = makeUser();
    vi.mocked(user.api.delete).mockRejectedValue(
      new Error('DELETE /debug/user-data 404: not found'),
    );

    const promise = cleanupUser(user);
    await vi.runAllTimersAsync();
    await expect(promise).resolves.toBeUndefined();

    expect(cancelSubsAndDeleteCustomer).toHaveBeenCalledOnce();
    expect(deleteUser).toHaveBeenCalledOnce();
    expect(findCustomerByEmail).toHaveBeenCalledOnce();
    expect(findUserByEmail).toHaveBeenCalledOnce();
  });

  it('throws when STRIPE_SECRET_KEY is missing', async () => {
    delete process.env.STRIPE_SECRET_KEY;
    await expect(cleanupUser(makeUser())).rejects.toThrow(/STRIPE_SECRET_KEY/);
  });

  it('throws when CLERK_SECRET_KEY is missing', async () => {
    delete process.env.CLERK_SECRET_KEY;
    await expect(cleanupUser(makeUser())).rejects.toThrow(/CLERK_SECRET_KEY/);
  });
});
