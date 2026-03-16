// frontend/src/hooks/useGatewayRpc.ts
"use client";

import { useCallback, useEffect, useRef } from "react";
import useSWR, { SWRConfiguration } from "swr";
import { useGateway } from "@/hooks/useGateway";

interface RpcResult<T = unknown> {
  data: T | undefined;
  error: Error | undefined;
  isLoading: boolean;
  mutate: () => void;
}

/**
 * Hook for read-only RPC calls via the gateway WebSocket (auto-fetched via SWR).
 *
 * Drop-in replacement for useContainerRpc. Same API, same return type.
 *
 * Usage:
 *   const { data, isLoading } = useGatewayRpc<HealthData>("health");
 *   const { data } = useGatewayRpc<AgentList>("agents.list");
 */
export function useGatewayRpc<T = unknown>(
  method: string | null,
  params?: Record<string, unknown>,
  config?: SWRConfiguration,
): RpcResult<T> {
  const { sendReq, onEvent } = useGateway();

  const fetcher = useCallback(
    async (key: string) => {
      // Split on first two "|" only — params JSON may contain pipe characters
      const firstPipe = key.indexOf("|");
      const secondPipe = key.indexOf("|", firstPipe + 1);
      const m = key.slice(firstPipe + 1, secondPipe);
      const paramStr = key.slice(secondPipe + 1);
      const parsedParams = paramStr ? JSON.parse(paramStr) : undefined;
      try {
        return (await sendReq(m, parsedParams)) as T;
      } catch (err) {
        // Match old behavior: 404-equivalent returns undefined
        if (err instanceof Error && err.message.includes("No container")) {
          return undefined;
        }
        throw err;
      }
    },
    [sendReq],
  );

  const swrKey = method
    ? `rpc|${method}|${params ? JSON.stringify(params) : ""}`
    : null;

  const { data, error, isLoading, mutate } = useSWR<T | undefined>(
    swrKey as string | null,
    fetcher as (key: string) => Promise<T | undefined>,
    {
      revalidateOnFocus: false,
      dedupingInterval: 10000,
      ...config,
    },
  );

  // Auto-revalidate when gateway pushes a matching event (throttled to
  // respect dedupingInterval — without this, high-frequency OpenClaw events
  // bypass SWR deduping and flood the backend with RPCs).
  const lastRevalidateRef = useRef(0);
  useEffect(() => {
    if (!method) return;
    return onEvent((event) => {
      if (method === event || method.startsWith(event + ".")) {
        const now = Date.now();
        if (now - lastRevalidateRef.current < 10_000) return;
        lastRevalidateRef.current = now;
        mutate();
      }
    });
  }, [method, onEvent, mutate]);

  return {
    data,
    error: error as Error | undefined,
    isLoading,
    mutate: () => {
      mutate();
    },
  };
}

/**
 * Hook for write RPC calls via the gateway WebSocket (imperative, not auto-fetched).
 *
 * Drop-in replacement for useContainerRpcMutation.
 *
 * Usage:
 *   const callRpc = useGatewayRpcMutation();
 *   await callRpc("config.set", { key: "value" });
 */
export function useGatewayRpcMutation() {
  const { sendReq } = useGateway();

  return useCallback(
    async <T = unknown>(
      method: string,
      params?: Record<string, unknown>,
    ): Promise<T> => {
      return (await sendReq(method, params)) as T;
    },
    [sendReq],
  );
}
