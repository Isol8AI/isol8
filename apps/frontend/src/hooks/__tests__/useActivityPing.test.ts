import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';

// Mock useGateway to observe send() calls.
const send = vi.fn();
vi.mock('../useGateway', () => ({
  useGateway: () => ({
    send,
    isConnected: true,
  }),
}));

function setVisibility(state: 'visible' | 'hidden') {
  Object.defineProperty(document, 'visibilityState', {
    value: state,
    configurable: true,
  });
  document.dispatchEvent(new Event('visibilitychange'));
}

async function importHook() {
  // Import late so the useGateway mock is already installed.
  const mod = await import('../useActivityPing');
  return mod.useActivityPing;
}

describe('useActivityPing', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    send.mockReset();
    setVisibility('visible');
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('sends one user_active when interacting on a visible tab', async () => {
    const useActivityPing = await importHook();
    renderHook(() => useActivityPing());

    act(() => {
      window.dispatchEvent(new MouseEvent('mousemove'));
    });
    act(() => {
      vi.advanceTimersByTime(6_000);  // drain interval
    });

    expect(send).toHaveBeenCalledTimes(1);
    expect(send).toHaveBeenCalledWith({ type: 'user_active' });
  });

  it('coalesces 100 mousemoves within the 60s gate', async () => {
    const useActivityPing = await importHook();
    renderHook(() => useActivityPing());

    act(() => {
      for (let i = 0; i < 100; i++) {
        window.dispatchEvent(new MouseEvent('mousemove'));
      }
    });
    act(() => {
      vi.advanceTimersByTime(6_000);
    });

    expect(send).toHaveBeenCalledTimes(1);
  });

  it('sends a second ping after 60s of additional interaction', async () => {
    const useActivityPing = await importHook();
    renderHook(() => useActivityPing());

    act(() => {
      window.dispatchEvent(new MouseEvent('mousemove'));
      vi.advanceTimersByTime(6_000);
    });
    expect(send).toHaveBeenCalledTimes(1);

    act(() => {
      vi.advanceTimersByTime(61_000);
      window.dispatchEvent(new MouseEvent('mousemove'));
      vi.advanceTimersByTime(6_000);
    });
    expect(send).toHaveBeenCalledTimes(2);
  });

  it('does not send while tab is hidden', async () => {
    const useActivityPing = await importHook();
    renderHook(() => useActivityPing());

    setVisibility('hidden');

    act(() => {
      window.dispatchEvent(new MouseEvent('mousemove'));
      vi.advanceTimersByTime(30_000);
    });

    expect(send).not.toHaveBeenCalled();
  });

  it('does not send when visible but idle', async () => {
    const useActivityPing = await importHook();
    renderHook(() => useActivityPing());

    act(() => {
      vi.advanceTimersByTime(120_000);
    });

    expect(send).not.toHaveBeenCalled();
  });

  it('resumes sending when tab becomes visible again during interaction', async () => {
    const useActivityPing = await importHook();
    renderHook(() => useActivityPing());

    setVisibility('hidden');
    act(() => {
      window.dispatchEvent(new MouseEvent('mousemove'));
      vi.advanceTimersByTime(30_000);
    });
    expect(send).not.toHaveBeenCalled();

    setVisibility('visible');
    act(() => {
      window.dispatchEvent(new MouseEvent('mousemove'));
      vi.advanceTimersByTime(6_000);
    });
    expect(send).toHaveBeenCalledTimes(1);
  });
});
