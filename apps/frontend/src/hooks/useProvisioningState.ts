"use client";

import { useCallback, useEffect, useState } from "react";
import useSWR from "swr";
import { useAuth } from "@clerk/nextjs";
import { BACKEND_URL, ApiError } from "@/lib/api";

/** Server-rendered blocked-state payload from /container/status (402). */
export interface BlockedPayload {
  code: string;
  title: string;
  message: string;
  action: {
    kind: "link";
    label: string;
    href: string;
    admin_only: boolean;
  };
  owner_role: "admin" | "member";
}

export interface ContainerInfo {
  service_name: string;
  status: string;
  substatus: string | null;
  // Other /container/status response fields preserved for downstream use.
  [key: string]: unknown;
}

export type ProvisioningPhase = "loading" | "normal" | "provision-needed" | "blocked";

export interface ProvisioningStateResult {
  phase: ProvisioningPhase;
  container: ContainerInfo | null;
  blocked: BlockedPayload | null;
  refreshInterval: number;
  refresh: () => void;
}

type FetchResult =
  | { kind: "container"; data: ContainerInfo }
  | { kind: "no-container" }
  | { kind: "blocked"; data: BlockedPayload };

/**
 * Owns the chat-page centerpiece state machine:
 *
 *   /status load
 *        |
 *  +-----+------+
 *  |   200      | 404                    | 402
 *  v            v                         v
 *  normal     provision-needed          blocked
 *
 * While blocked, polls fast (5s) for the first minute, then 30s.
 * `refresh()` resets to 5s and re-polls immediately.
 */
export function useProvisioningState(): ProvisioningStateResult {
  const { getToken, isSignedIn } = useAuth();
  // Two-phase blocked-state polling cadence: 5s for the first minute, then
  // 30s. `blockedFastPhase` is a *generation counter* — each new blocked
  // entry (or manual refresh) bumps it, the effect below tracks generations
  // and flips the cadence flag after 60s. Storing as a counter keeps the
  // effect derived purely from inputs (no setState-from-effect against the
  // same flag the effect reads) so `react-hooks/set-state-in-effect` is happy.
  const [blockedGen, setBlockedGen] = useState<number>(0);
  const [slowAfterGen, setSlowAfterGen] = useState<number>(-1);

  const fetcher = useCallback(
    async (url: string): Promise<FetchResult> => {
      const token = await getToken();
      if (!token) throw new Error("No auth token");
      const res = await fetch(`${BACKEND_URL}${url}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.status === 404) return { kind: "no-container" };
      if (res.status === 402) {
        // FastAPI's HTTPException(detail=...) serializes to
        // {"detail": <whatever was passed>}. Backend passes
        // gate.to_payload() which is {"blocked": {...}}, so the wire
        // shape is {"detail": {"blocked": {...}}}. Read from the
        // detail envelope; fall back to a top-level "blocked" key
        // (used by some test fixtures and to be defensive about
        // transport quirks) so this hook stays robust either way.
        const body = await res.json();
        const envelope =
          (body && typeof body === "object" ? (body as Record<string, unknown>) : {}) || {};
        const detail = envelope.detail;
        const blocked =
          detail && typeof detail === "object" && "blocked" in (detail as object)
            ? (detail as { blocked: BlockedPayload }).blocked
            : (envelope.blocked as BlockedPayload | undefined);
        if (!blocked) {
          // Defensive: 402 without a recognizable blocked payload — surface
          // as ApiError so we don't silently render an empty blocked screen.
          throw new ApiError(res.status, body);
        }
        return { kind: "blocked", data: blocked };
      }
      if (!res.ok) {
        // Unexpected status — surface as ApiError so downstream sees it.
        let body: unknown = null;
        try {
          body = await res.json();
        } catch {
          // ignore
        }
        throw new ApiError(res.status, body);
      }
      const data = (await res.json()) as ContainerInfo;
      return { kind: "container", data };
    },
    [getToken],
  );

  const { data, mutate } = useSWR<FetchResult>(
    isSignedIn ? "/container/status" : null,
    fetcher,
    {
      revalidateOnFocus: false,
      // Function form lets SWR pass the latest data; while blocked,
      // fast-poll for the first minute (slowAfterGen < blockedGen means
      // the 60s timer hasn't fired yet for the current generation), then
      // drop to 30s. Avoids referencing `data` in this options block (it
      // isn't in scope yet).
      refreshInterval: (latest) =>
        latest?.kind === "blocked"
          ? slowAfterGen < blockedGen
            ? 5_000
            : 30_000
          : 0,
    },
  );

  // The timer effect schedules a fresh 60s timeout each time the
  // *generation* changes while blocked. `blockedGen` is bumped:
  //   - on the rising edge into blocked (tracked by a setState-in-render
  //     pattern that triggers exactly one extra render at the transition;
  //     React handles this idiomatically — see "Storing information from
  //     previous renders" in the React docs)
  //   - on every `refresh()` call
  //
  // Codex P2 on PR #519: the previous `[isBlocked]`-only effect never
  // re-fired on subsequent refreshes, so a manual refresh after the
  // first minute could leave polling stuck at 5s indefinitely.
  const isBlocked = data?.kind === "blocked";
  const [prevIsBlocked, setPrevIsBlocked] = useState(false);
  if (isBlocked !== prevIsBlocked) {
    // setState-during-render is the React-recommended way to derive a
    // value from a prop/state change without an extra round-trip
    // through useEffect. It also keeps us clear of
    // `react-hooks/set-state-in-effect`. Only the "rising edge" bumps
    // the generation; the falling edge just resets the tracker.
    setPrevIsBlocked(isBlocked);
    if (isBlocked) setBlockedGen((g) => g + 1);
  }

  useEffect(() => {
    if (!isBlocked) return;
    const myGen = blockedGen;
    const t = setTimeout(() => setSlowAfterGen(myGen), 60_000);
    return () => clearTimeout(t);
  }, [isBlocked, blockedGen]);

  const refresh = useCallback(() => {
    // Manual refresh resets the fast-poll window: bump the generation so
    // (a) `slowAfterGen < blockedGen` again (back to 5s), and (b) the
    // timer effect re-fires for the new generation and schedules a fresh
    // 60s timeout.
    setBlockedGen((g) => g + 1);
    mutate();
  }, [mutate]);

  const refreshInterval = isBlocked ? (slowAfterGen < blockedGen ? 5_000 : 30_000) : 0;

  if (!data) {
    return { phase: "loading", container: null, blocked: null, refreshInterval: 0, refresh };
  }
  if (data.kind === "container") {
    return { phase: "normal", container: data.data, blocked: null, refreshInterval, refresh };
  }
  if (data.kind === "no-container") {
    return { phase: "provision-needed", container: null, blocked: null, refreshInterval, refresh };
  }
  return { phase: "blocked", container: null, blocked: data.data, refreshInterval, refresh };
}
