"use client";

import useSWR, { type SWRConfiguration, type SWRResponse } from "swr";
import { useApi } from "@/lib/api";

/**
 * Hook for the teams BFF surface (`/api/v1/teams/*`).
 *
 * Centralizes all Clerk-authenticated calls into the BFF so re-routing the
 * base URL is a one-line change. Panels in `src/components/teams/panels/*`
 * use this hook for both reads (SWR-cached) and writes (one-shot mutations).
 *
 * Usage:
 *   const { read, post, patch, del } = useTeamsApi();
 *   const { data, isLoading, error, mutate } = read<AgentList>("/agents");
 *   await post("/agents", { name, role });
 *
 * Note on rules-of-hooks: `read` calls `useSWR` internally, so it is a hook
 * itself. Call it unconditionally at the top of a component (the standard SWR
 * usage pattern). Do NOT wrap a `read(...)` call in a conditional.
 *
 * The SWR cache key is `/teams${path}`, which guarantees uniqueness per path
 * so different panels never share state.
 */
export function useTeamsApi() {
  const api = useApi();

  // Named `useRead` (use-prefix) so the react-hooks/rules-of-hooks lint accepts
  // the internal `useSWR` call. Exposed on the returned object as `read` for
  // ergonomic panel usage. Panels MUST call `read(...)` unconditionally at the
  // top of their component body (standard SWR rules of hooks apply).
  function useRead<T = unknown>(path: string, swrOpts?: SWRConfiguration<T>): SWRResponse<T> {
    return useSWR<T>(
      `/teams${path}`,
      () => api.get(`/teams${path}`) as Promise<T>,
      swrOpts,
    );
  }

  async function post<T = unknown>(path: string, body: unknown): Promise<T> {
    return (await api.post(`/teams${path}`, body)) as T;
  }

  // `useApi()` exposes `put` (not `patch`); the BFF accepts PUT for partial
  // updates on these resources, so we surface this method as `patch` for
  // panel-call ergonomics and route it via PUT under the hood.
  async function patch<T = unknown>(path: string, body: unknown): Promise<T> {
    return (await api.put(`/teams${path}`, body)) as T;
  }

  async function del<T = unknown>(path: string): Promise<T> {
    return (await api.del(`/teams${path}`)) as T;
  }

  return { read: useRead, post, patch, del };
}
