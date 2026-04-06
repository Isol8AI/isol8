"use client";
import useSWR from "swr";
import { useApi } from "@/lib/api";
import { useCallback, useMemo } from "react";

interface PaperclipStatus {
  enabled: boolean;
  healthy: boolean;
  eligible: boolean;
}

export function usePaperclipStatus() {
  const api = useApi();
  const { data, error, isLoading, mutate } = useSWR<PaperclipStatus>(
    "/paperclip/status",
    () => api.get("/paperclip/status") as Promise<PaperclipStatus>,
    { dedupingInterval: 10_000 },
  );
  return {
    status: data ?? { enabled: false, healthy: false, eligible: false },
    isLoading,
    error,
    refresh: mutate,
  };
}

export function usePaperclipApi<T = unknown>(path: string | null) {
  const api = useApi();
  const { data, error, isLoading, mutate } = useSWR<T>(
    path ? `/paperclip/proxy/${path}` : null,
    () => api.get(`/paperclip/proxy/${path}`) as Promise<T>,
    { dedupingInterval: 5_000 },
  );
  return { data, error, isLoading, refresh: mutate };
}

export function usePaperclipMutation() {
  const api = useApi();
  const post = useCallback(
    async <T = unknown>(path: string, body?: unknown): Promise<T> =>
      api.post(`/paperclip/proxy/${path}`, body) as Promise<T>,
    [api],
  );
  const put = useCallback(
    async <T = unknown>(path: string, body?: unknown): Promise<T> =>
      api.put(`/paperclip/proxy/${path}`, body) as Promise<T>,
    [api],
  );
  const del = useCallback(
    async <T = unknown>(path: string): Promise<T> =>
      api.del(`/paperclip/proxy/${path}`) as Promise<T>,
    [api],
  );
  return useMemo(() => ({ post, put, del }), [post, put, del]);
}

export function usePaperclipEnable() {
  const api = useApi();
  const { refresh } = usePaperclipStatus();
  const enable = useCallback(async () => {
    const r = await api.post("/paperclip/enable", undefined);
    await refresh();
    return r;
  }, [api, refresh]);
  const disable = useCallback(async () => {
    const r = await api.post("/paperclip/disable", undefined);
    await refresh();
    return r;
  }, [api, refresh]);
  return { enable, disable };
}
