import { describe, it, expect, vi, beforeEach } from 'vitest';

// Reset module cache so each test gets fresh module state
beforeEach(() => {
  vi.resetModules();
  vi.clearAllMocks();
});

describe('deprovisionIfExists', () => {
  it('resolves without throwing when container does not exist (404)', async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 404 });
    const { deprovisionIfExists } = await import('../../e2e/helpers/provision');
    await expect(deprovisionIfExists('http://api', async () => 'token')).resolves.toBeUndefined();
  });

  it('resolves without throwing when ECS errors (503)', async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 503 });
    const { deprovisionIfExists } = await import('../../e2e/helpers/provision');
    await expect(deprovisionIfExists('http://api', async () => 'token')).resolves.toBeUndefined();
  });

  it('resolves when DELETE succeeds (200)', async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: true, status: 200 });
    const { deprovisionIfExists } = await import('../../e2e/helpers/provision');
    await expect(deprovisionIfExists('http://api', async () => 'token')).resolves.toBeUndefined();
  });

  it('resolves without throwing when auth fails (401)', async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 401 });
    const { deprovisionIfExists } = await import('../../e2e/helpers/provision');
    await expect(deprovisionIfExists('http://api', async () => 'token')).resolves.toBeUndefined();
  });

  it('throws on unexpected error (500)', async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 500 });
    const { deprovisionIfExists } = await import('../../e2e/helpers/provision');
    await expect(deprovisionIfExists('http://api', async () => 'token')).rejects.toThrow('Unexpected deprovision response: 500');
  });
});

describe('waitForRunning', () => {
  it('resolves when status is running', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ status: 'running', substatus: 'gateway_healthy' }),
    });
    const { waitForRunning } = await import('../../e2e/helpers/provision');
    await expect(waitForRunning('http://api', async () => 'token', 5000)).resolves.toBeUndefined();
  });

  it('throws when status is error', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ status: 'error', substatus: null, last_error: 'task failed' }),
    });
    const { waitForRunning } = await import('../../e2e/helpers/provision');
    await expect(waitForRunning('http://api', async () => 'token', 5000)).rejects.toThrow('Container entered error state');
  });

  it('throws when timeout exceeded before running', async () => {
    vi.useFakeTimers();
    // fetch always returns "provisioning" so the loop never exits early
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ status: 'provisioning', substatus: 'starting' }),
    });
    const { waitForRunning } = await import('../../e2e/helpers/provision');
    // Advance time past the deadline and assert the rejection concurrently
    // so the promise is never left unhandled between awaits
    await expect(
      Promise.all([
        waitForRunning('http://api', async () => 'token', 100),
        vi.runAllTimersAsync(),
      ]),
    ).rejects.toThrow('timeout');
    vi.useRealTimers();
  });

  it('throws immediately on non-ok, non-503 response', async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 401 });
    const { waitForRunning } = await import('../../e2e/helpers/provision');
    await expect(waitForRunning('http://api', async () => 'token', 5000)).rejects.toThrow('Unexpected poll response: 401');
  });

  it('continues polling on 503 (transient unavailable)', async () => {
    // First call returns 503, second returns running
    global.fetch = vi
      .fn()
      .mockResolvedValueOnce({ ok: false, status: 503 })
      .mockResolvedValue({
        ok: true,
        json: async () => ({ status: 'running', substatus: 'gateway_healthy' }),
      });
    const { waitForRunning } = await import('../../e2e/helpers/provision');
    await expect(waitForRunning('http://api', async () => 'token', 10000)).resolves.toBeUndefined();
  });
});
