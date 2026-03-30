"use client";

import { useCallback } from "react";
import useSWR from "swr";
import { useAuth } from "@clerk/nextjs";
import { BACKEND_URL } from "@/lib/api";

export interface ContainerStatus {
  service_name: string;
  status: string;
  substatus: string | null;
  created_at: string | null;
  updated_at: string | null;
  region: string;
  last_error: string | null;
  last_error_at: string | null;
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
      revalidateOnFocus: false,
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
