import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock the stripe module so we control the instance returned by `new Stripe(...)`
vi.mock('stripe', () => {
  const mockSubscriptionsCancel = vi.fn();
  const mockSubscriptionsList = vi.fn();
  const mockSubscriptionsCreate = vi.fn();
  const mockCustomersList = vi.fn();
  const mockCustomersCreate = vi.fn();
  const mockPaymentMethodsAttach = vi.fn();
  const mockCustomersUpdate = vi.fn();

  const mockInstance = {
    customers: {
      list: mockCustomersList,
      create: mockCustomersCreate,
      update: mockCustomersUpdate,
    },
    subscriptions: {
      list: mockSubscriptionsList,
      cancel: mockSubscriptionsCancel,
      create: mockSubscriptionsCreate,
    },
    paymentMethods: {
      attach: mockPaymentMethodsAttach,
    },
  };

  const MockStripe = vi.fn(() => mockInstance);

  // Expose mocks via the constructor function so tests can access them
  (MockStripe as unknown as Record<string, unknown>)._instance = mockInstance;
  (MockStripe as unknown as Record<string, unknown>)._mocks = {
    subscriptionsCancel: mockSubscriptionsCancel,
    subscriptionsList: mockSubscriptionsList,
    subscriptionsCreate: mockSubscriptionsCreate,
    customersList: mockCustomersList,
    customersCreate: mockCustomersCreate,
    paymentMethodsAttach: mockPaymentMethodsAttach,
    customersUpdate: mockCustomersUpdate,
  };

  return { default: MockStripe };
});

// Reset module cache and mocks before each test
beforeEach(() => {
  vi.clearAllMocks();
});

async function getMocks() {
  const Stripe = (await import('stripe')).default as unknown as {
    _mocks: {
      subscriptionsCancel: ReturnType<typeof vi.fn>;
      subscriptionsList: ReturnType<typeof vi.fn>;
      subscriptionsCreate: ReturnType<typeof vi.fn>;
      customersList: ReturnType<typeof vi.fn>;
      customersCreate: ReturnType<typeof vi.fn>;
      paymentMethodsAttach: ReturnType<typeof vi.fn>;
      customersUpdate: ReturnType<typeof vi.fn>;
    };
  };
  return Stripe._mocks;
}

describe('cancelSubscriptionIfExists', () => {
  it('no-op when no customers found', async () => {
    const mocks = await getMocks();
    mocks.customersList.mockResolvedValue({ data: [] });

    const { cancelSubscriptionIfExists } = await import('../../e2e/helpers/stripe');
    await expect(cancelSubscriptionIfExists('nobody@example.com')).resolves.toBeUndefined();

    expect(mocks.subscriptionsList).not.toHaveBeenCalled();
    expect(mocks.subscriptionsCancel).not.toHaveBeenCalled();
  });

  it('no-op when customer has no subscriptions', async () => {
    const mocks = await getMocks();
    mocks.customersList.mockResolvedValue({ data: [{ id: 'cus_123' }] });
    mocks.subscriptionsList.mockResolvedValue({ data: [] });

    const { cancelSubscriptionIfExists } = await import('../../e2e/helpers/stripe');
    await expect(cancelSubscriptionIfExists('test@example.com')).resolves.toBeUndefined();

    expect(mocks.subscriptionsCancel).not.toHaveBeenCalled();
  });

  it('cancels active subscription', async () => {
    const mocks = await getMocks();
    mocks.customersList.mockResolvedValue({ data: [{ id: 'cus_123' }] });
    mocks.subscriptionsList.mockResolvedValue({
      data: [{ id: 'sub_active', status: 'active' }],
    });
    mocks.subscriptionsCancel.mockResolvedValue({ id: 'sub_active', status: 'canceled' });

    const { cancelSubscriptionIfExists } = await import('../../e2e/helpers/stripe');
    await expect(cancelSubscriptionIfExists('test@example.com')).resolves.toBeUndefined();

    expect(mocks.subscriptionsCancel).toHaveBeenCalledWith('sub_active');
  });

  it('skips already-canceled subscription', async () => {
    const mocks = await getMocks();
    mocks.customersList.mockResolvedValue({ data: [{ id: 'cus_123' }] });
    mocks.subscriptionsList.mockResolvedValue({
      data: [{ id: 'sub_old', status: 'canceled' }],
    });

    const { cancelSubscriptionIfExists } = await import('../../e2e/helpers/stripe');
    await expect(cancelSubscriptionIfExists('test@example.com')).resolves.toBeUndefined();

    expect(mocks.subscriptionsCancel).not.toHaveBeenCalled();
  });
});

describe('createSubscription', () => {
  it('reuses existing customer without creating a new one', async () => {
    const mocks = await getMocks();
    mocks.customersList.mockResolvedValue({ data: [{ id: 'cus_existing' }] });
    mocks.paymentMethodsAttach.mockResolvedValue({});
    mocks.customersUpdate.mockResolvedValue({});
    const fakeSub = { id: 'sub_new', status: 'active' };
    mocks.subscriptionsCreate.mockResolvedValue(fakeSub);

    const { createSubscription } = await import('../../e2e/helpers/stripe');
    const result = await createSubscription('existing@example.com', 'price_starter');

    expect(mocks.customersCreate).not.toHaveBeenCalled();
    expect(mocks.subscriptionsCreate).toHaveBeenCalledWith(
      expect.objectContaining({ customer: 'cus_existing' }),
    );
    expect(result).toEqual(fakeSub);
  });

  it('creates a new customer when none exists', async () => {
    const mocks = await getMocks();
    mocks.customersList.mockResolvedValue({ data: [] });
    mocks.customersCreate.mockResolvedValue({ id: 'cus_new' });
    mocks.paymentMethodsAttach.mockResolvedValue({});
    mocks.customersUpdate.mockResolvedValue({});
    const fakeSub = { id: 'sub_new', status: 'active' };
    mocks.subscriptionsCreate.mockResolvedValue(fakeSub);

    const { createSubscription } = await import('../../e2e/helpers/stripe');
    const result = await createSubscription('new@example.com', 'price_starter');

    expect(mocks.customersCreate).toHaveBeenCalledWith({ email: 'new@example.com' });
    expect(mocks.subscriptionsCreate).toHaveBeenCalledWith(
      expect.objectContaining({ customer: 'cus_new' }),
    );
    expect(result).toEqual(fakeSub);
  });

  it('returns the created subscription', async () => {
    const mocks = await getMocks();
    mocks.customersList.mockResolvedValue({ data: [{ id: 'cus_abc' }] });
    mocks.paymentMethodsAttach.mockResolvedValue({});
    mocks.customersUpdate.mockResolvedValue({});
    const fakeSub = { id: 'sub_xyz', status: 'trialing' };
    mocks.subscriptionsCreate.mockResolvedValue(fakeSub);

    const { createSubscription } = await import('../../e2e/helpers/stripe');
    const result = await createSubscription('user@example.com', 'price_pro');

    expect(result).toEqual(fakeSub);
  });
});

describe('waitForSubscriptionActive', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('resolves when is_subscribed is true', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ is_subscribed: true }),
    });

    const { waitForSubscriptionActive } = await import('../../e2e/helpers/stripe');
    await expect(
      waitForSubscriptionActive('http://api', 'token', 10000),
    ).resolves.toBeUndefined();
  });

  it('swallows 503 and continues polling', async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValueOnce({ ok: false, status: 503 })
      .mockResolvedValue({
        ok: true,
        json: async () => ({ is_subscribed: true }),
      });

    const { waitForSubscriptionActive } = await import('../../e2e/helpers/stripe');
    await expect(
      Promise.all([
        waitForSubscriptionActive('http://api', 'token', 30000),
        vi.runAllTimersAsync(),
      ]),
    ).resolves.toBeDefined();
  });

  it('throws immediately on non-ok, non-503 response', async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 401 });

    const { waitForSubscriptionActive } = await import('../../e2e/helpers/stripe');
    await expect(waitForSubscriptionActive('http://api', 'token', 10000)).rejects.toThrow('401');
  });

  it('throws descriptive timeout error when deadline exceeded', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ is_subscribed: false }),
    });

    const { waitForSubscriptionActive } = await import('../../e2e/helpers/stripe');
    await expect(
      Promise.all([
        waitForSubscriptionActive('http://api', 'token', 100),
        vi.runAllTimersAsync(),
      ]),
    ).rejects.toThrow('timeout');
  });
});
