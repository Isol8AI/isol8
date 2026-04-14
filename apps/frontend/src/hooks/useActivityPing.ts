import { useEffect, useRef } from 'react';
import { useGateway } from './useGateway';

const PING_INTERVAL_MS = 60_000;
const DRAIN_INTERVAL_MS = 5_000;

/**
 * Subset of the gateway API this hook depends on. The real `useGateway`
 * context is expected to expose a raw `send(message)` method alongside
 * `isConnected`; the wiring that adds it lives in a separate task. `send`
 * is marked optional because the hook ships before that wiring — a
 * runtime guard keeps the hook a no-op until `send` is present, rather
 * than throwing a `TypeError` on the first drain.
 */
interface ActivityGateway {
  send?: (message: { type: 'user_active' }) => void;
  isConnected: boolean;
}

/**
 * Emits a throttled `user_active` WebSocket message while the user is
 * interacting with a visible tab. Used by the backend scale-to-zero reaper
 * to decide when to stop free-tier containers.
 *
 * At most one `send` per `PING_INTERVAL_MS`. Never sends while the tab is
 * hidden. Interaction events (click, keydown, mousemove, scroll) set a
 * pending flag; a periodic drain at `DRAIN_INTERVAL_MS` checks the flag,
 * the visibility state, and the last-ping gate before sending.
 */
export function useActivityPing(): void {
  const { send, isConnected } = useGateway() as unknown as ActivityGateway;
  const lastPingRef = useRef(0);
  const pendingRef = useRef(false);

  useEffect(() => {
    if (!isConnected) return;

    const onInteraction = () => {
      if (document.visibilityState !== 'visible') return;
      pendingRef.current = true;
    };

    const drain = () => {
      if (!pendingRef.current) return;
      if (document.visibilityState !== 'visible') return;
      if (typeof send !== 'function') return;
      const now = Date.now();
      if (now - lastPingRef.current < PING_INTERVAL_MS) return;
      send({ type: 'user_active' });
      lastPingRef.current = now;
      pendingRef.current = false;
    };

    const drainer = window.setInterval(drain, DRAIN_INTERVAL_MS);

    const events = ['click', 'keydown', 'mousemove', 'scroll'] as const;
    events.forEach((e) =>
      window.addEventListener(e, onInteraction, { passive: true }),
    );
    document.addEventListener('visibilitychange', onInteraction);

    return () => {
      window.clearInterval(drainer);
      events.forEach((e) => window.removeEventListener(e, onInteraction));
      document.removeEventListener('visibilitychange', onInteraction);
    };
  }, [isConnected, send]);
}
