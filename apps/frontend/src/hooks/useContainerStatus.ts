"use client";

import { useCallback } from "react";
import useSWR from "swr";
import { useAuth } from "@clerk/nextjs";
import { BACKEND_URL } from "@/lib/api";

/**
 * Cold-start phase from `routers/container.py::_resolve_cold_start_phase`.
 * - `provisioning`: ECS task hasn't reached RUNNING yet (image pull, ENI
 *   attach, container init). Today this can be 60–120 s on a fresh service.
 * - `starting`: ECS task is RUNNING but the backend's gateway pool hasn't
 *   completed the OpenClaw 4.5 signed-device handshake + health RPC. This
 *   is where the long wait lives — gateway boot (≈30 s), then sidecars
 *   (channels + qmd memory init) which can run several minutes.
 * - `ready`: pool has a live, healthy connection to openclaw — chat works.
 */
export type ColdStartPhase = "provisioning" | "starting" | "ready";

export interface ContainerStatus {
  service_name: string;
  status: string;
  substatus: string | null;
  created_at: string | null;
  updated_at: string | null;
  region: string;
  last_error: string | null;
  last_error_at: string | null;
  /** Cold-start phase. Optional for backwards compat with old backends. */
  phase?: ColdStartPhase;
}

interface UseContainerStatusOptions {
  /** Polling interval in ms. 0 = no polling. Default: 0 */
  refreshInterval?: number;
  /** Whether to actively fetch. Default: true */
  enabled?: boolean;
}

export function useContainerStatus(options: UseContainerStatusOptions = {}) {
  const { refreshInterval = 0, enabled = true } = options;
  const { getToken, isSignedIn } = useAuth();

  const fetcher = useCallback(
    async (url: string) => {
      const token = await getToken();
      if (!token) throw new Error("No auth token");

      const res = await fetch(`${BACKEND_URL}${url}`, {
        headers: { Authorization: `Bearer ${token}` },
      });

      if (res.status === 404) return null;
      if (!res.ok) throw new Error("Failed to fetch container status");
      return res.json();
    },
    [getToken],
  );

  const { data, error, isLoading, mutate } = useSWR<ContainerStatus | null>(
    isSignedIn && enabled ? "/container/status" : null,
    fetcher,
    {
      // Revalidate when the tab regains focus. Without this, the chat
      // page can show a stale "running" container minutes after the row
      // is gone — observed when a container is deleted server-side
      // (admin tooling, scale-to-zero, AWS console cleanup) while the
      // tab was in the background.
      revalidateOnFocus: true,
      dedupingInterval: Math.min(refreshInterval || 30000, 30000),
      refreshInterval: refreshInterval || 0,
    },
  );

  const refresh = useCallback(() => mutate(), [mutate]);

  return {
    container: data,
    isLoading,
    error: error as Error | undefined,
    refresh,
  };
}
