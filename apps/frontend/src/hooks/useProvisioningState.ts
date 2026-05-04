"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
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
  const [blockedSinceMs, setBlockedSinceMs] = useState<number | null>(null);

  const fetcher = useCallback(
    async (url: string): Promise<FetchResult> => {
      const token = await getToken();
      if (!token) throw new Error("No auth token");
      const res = await fetch(`${BACKEND_URL}${url}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.status === 404) return { kind: "no-container" };
      if (res.status === 402) {
        const body = await res.json();
        return { kind: "blocked", data: body.blocked as BlockedPayload };
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

  const refreshInterval = useMemo(() => {
    if (blockedSinceMs === null) return 0;
    const elapsed = Date.now() - blockedSinceMs;
    return elapsed < 60_000 ? 5_000 : 30_000;
  }, [blockedSinceMs]);

  const { data, mutate } = useSWR<FetchResult>(
    isSignedIn ? "/container/status" : null,
    fetcher,
    {
      revalidateOnFocus: false,
      refreshInterval,
    },
  );

  useEffect(() => {
    if (data?.kind === "blocked") {
      if (blockedSinceMs === null) setBlockedSinceMs(Date.now());
    } else if (blockedSinceMs !== null) {
      setBlockedSinceMs(null);
    }
  }, [data, blockedSinceMs]);

  const refresh = useCallback(() => {
    setBlockedSinceMs(Date.now());
    mutate();
  }, [mutate]);

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
