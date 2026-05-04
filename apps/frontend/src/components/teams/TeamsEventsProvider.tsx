"use client";

import { useEffect, useRef } from "react";
import { useSWRConfig } from "swr";
import { useGateway } from "@/hooks/useGateway";

/**
 * Mounts inside TeamsLayout (which is inside GatewayProvider). Subscribes
 * to Paperclip live events forwarded by the BFF and invalidates SWR cache
 * keys per event type so panels rerender automatically.
 *
 * Spec: docs/superpowers/specs/2026-05-04-teams-realtime-design.md
 *
 * Pattern mirrors Paperclip's own LiveUpdatesProvider — a single mount
 * point owns all realtime invalidation; panels themselves stay free of
 * realtime concerns.
 */

const ALL_KEYS = [
  "/teams/dashboard",
  "/teams/activity",
  "/teams/inbox",
  "/teams/issues",
  "/teams/agents",
];

const EVENT_KEY_MAP: Record<string, string[]> = {
  "teams.activity.logged": [
    "/teams/dashboard", "/teams/activity", "/teams/inbox", "/teams/issues",
  ],
  "teams.agent.status": ["/teams/dashboard", "/teams/agents"],
  "teams.heartbeat.run.queued": ["/teams/dashboard", "/teams/inbox"],
  "teams.heartbeat.run.status": ["/teams/dashboard", "/teams/inbox"],
  // Run-event/log only matter when run-detail is open. SWR mutate on a
  // path-prefix is not natively supported; the panels for those routes
  // can subscribe themselves later. For now, no global invalidation.
  "teams.heartbeat.run.event": [],
  "teams.heartbeat.run.log": [],
};

export function TeamsEventsProvider({ children }: { children: React.ReactNode }) {
  const { isConnected, send, onEvent } = useGateway();
  const { mutate } = useSWRConfig();
  // null = never observed; false = observed disconnected; true = observed connected.
  // Full invalidation only fires on a tracked false→true transition (true reconnect),
  // NOT on the first mount when we were already connected.
  const wasConnectedRef = useRef<boolean | null>(null);

  // (re)subscribe + full invalidation on connect / reconnect.
  useEffect(() => {
    if (!isConnected) {
      wasConnectedRef.current = false;
      return;
    }
    send({ type: "teams.subscribe" });
    if (wasConnectedRef.current === false) {
      // Reconnect path: refetch everything because Paperclip's WS has no
      // replay cursor and we may have missed events while disconnected.
      for (const key of ALL_KEYS) mutate(key);
    }
    wasConnectedRef.current = true;
  }, [isConnected, send, mutate]);

  // Wire event listener.
  useEffect(() => {
    const unsub = onEvent((event, _data) => {
      if (!event.startsWith("teams.")) return;
      if (event === "teams.stream.resumed") {
        for (const key of ALL_KEYS) mutate(key);
        return;
      }
      const keys = EVENT_KEY_MAP[event];
      if (!keys || keys.length === 0) return;
      for (const key of keys) mutate(key);
    });
    return () => {
      unsub();
    };
  }, [onEvent, mutate]);

  // Best-effort unsubscribe on unmount.
  useEffect(() => {
    return () => {
      send({ type: "teams.unsubscribe" });
    };
  }, [send]);

  return <>{children}</>;
}
