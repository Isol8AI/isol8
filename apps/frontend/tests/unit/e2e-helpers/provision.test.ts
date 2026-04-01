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
    await expect(deprovisionIfExists('http://api', 'token')).resolves.toBeUndefined();
  });

  it('resolves without throwing when ECS errors (503)', async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 503 });
    const { deprovisionIfExists } = await import('../../e2e/helpers/provision');
    await expect(deprovisionIfExists('http://api', 'token')).resolves.toBeUndefined();
  });

  it('resolves when DELETE succeeds (200)', async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: true, status: 200 });
    const { deprovisionIfExists } = await import('../../e2e/helpers/provision');
    await expect(deprovisionIfExists('http://api', 'token')).resolves.toBeUndefined();
  });

  it('throws on unexpected error (500)', async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 500 });
    const { deprovisionIfExists } = await import('../../e2e/helpers/provision');
    await expect(deprovisionIfExists('http://api', 'token')).rejects.toThrow('Unexpected deprovision response: 500');
  });
});

describe('waitForRunning', () => {
  it('resolves when status is running', async () => {
    vi.useFakeTimers();
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ status: 'running', substatus: 'gateway_healthy' }),
    });
    const { waitForRunning } = await import('../../e2e/helpers/provision');
    await expect(waitForRunning('http://api', 'token', 5000)).resolves.toBeUndefined();
    vi.useRealTimers();
  });

  it('throws when status is error', async () => {
    vi.useFakeTimers();
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ status: 'error', substatus: null, last_error: 'task failed' }),
    });
    const { waitForRunning } = await import('../../e2e/helpers/provision');
    await expect(waitForRunning('http://api', 'token', 5000)).rejects.toThrow('Container entered error state');
    vi.useRealTimers();
  });

  it('throws when timeout exceeded before running', async () => {
    // Use real timers — deadline of 1ms will expire immediately
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ status: 'provisioning', substatus: 'starting' }),
    });
    const { waitForRunning } = await import('../../e2e/helpers/provision');
    await expect(waitForRunning('http://api', 'token', 1)).rejects.toThrow('timeout');
  });
});
