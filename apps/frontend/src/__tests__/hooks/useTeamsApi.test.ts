import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";

// Hoisted mocks so we can introspect call args from inside tests. `useApi()`
// must return the SAME object identity each render (otherwise the SWR fetcher
// closure would be different per render and cause infinite re-fetch loops in
// tests). We do that by constructing the mock methods once at the module level.
const { mockGet, mockPost, mockPut, mockDel, mockApi } = vi.hoisted(() => {
  const mockGet = vi.fn();
  const mockPost = vi.fn();
  const mockPut = vi.fn();
  const mockDel = vi.fn();
  return {
    mockGet,
    mockPost,
    mockPut,
    mockDel,
    mockApi: {
      get: mockGet,
      post: mockPost,
      put: mockPut,
      del: mockDel,
      // Unused by useTeamsApi, included for type compatibility:
      syncUser: vi.fn(),
      patchConfig: vi.fn(),
      uploadFiles: vi.fn(),
      saveWorkspaceFile: vi.fn(),
    },
  };
});

vi.mock("@/lib/api", () => ({
  useApi: () => mockApi,
}));

// Reset SWR cache between tests so `read()` doesn't return a stale value
// keyed by a path another test already populated.
import { SWRConfig } from "swr";
import { createElement, type ReactNode } from "react";

function wrapper({ children }: { children: ReactNode }) {
  return createElement(
    SWRConfig,
    { value: { provider: () => new Map(), dedupingInterval: 0 } },
    children,
  );
}

import { useTeamsApi } from "@/hooks/useTeamsApi";

describe("useTeamsApi", () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockPost.mockReset();
    mockPut.mockReset();
    mockDel.mockReset();
  });

  describe("read", () => {
    it("prefixes /teams in the request path and returns SWR data", async () => {
      mockGet.mockResolvedValueOnce({ ok: true });
      const { result } = renderHook(() => useTeamsApi().read<{ ok: boolean }>("/agents"), {
        wrapper,
      });

      await waitFor(() => expect(result.current.data).toEqual({ ok: true }));
      expect(mockGet).toHaveBeenCalledWith("/teams/agents");
    });

    it("uses a unique SWR cache key per path", async () => {
      mockGet.mockImplementation((p: string) =>
        Promise.resolve(p === "/teams/agents" ? { list: "agents" } : { list: "issues" }),
      );

      function Both() {
        const api = useTeamsApi();
        const a = api.read<{ list: string }>("/agents");
        const b = api.read<{ list: string }>("/issues");
        return { a, b };
      }

      const { result } = renderHook(Both, { wrapper });

      await waitFor(() => expect(result.current.a.data).toEqual({ list: "agents" }));
      await waitFor(() => expect(result.current.b.data).toEqual({ list: "issues" }));
      expect(mockGet).toHaveBeenCalledWith("/teams/agents");
      expect(mockGet).toHaveBeenCalledWith("/teams/issues");
    });

    it("propagates fetcher errors to SWR.error", async () => {
      const boom = new Error("boom");
      mockGet.mockRejectedValueOnce(boom);
      const { result } = renderHook(() => useTeamsApi().read("/agents"), { wrapper });

      await waitFor(() => expect(result.current.error).toBe(boom));
    });
  });

  describe("post", () => {
    it("prefixes /teams and forwards body to api.post", async () => {
      mockPost.mockResolvedValueOnce({ id: "x" });
      const { result } = renderHook(() => useTeamsApi(), { wrapper });

      const body = { name: "x", role: "engineer" };
      const resp = await result.current.post<{ id: string }>("/agents", body);

      expect(resp).toEqual({ id: "x" });
      expect(mockPost).toHaveBeenCalledWith("/teams/agents", body);
    });
  });

  describe("patch", () => {
    it("routes via api.put under the hood (useApi exposes put, not patch)", async () => {
      mockPut.mockResolvedValueOnce({ updated: true });
      const { result } = renderHook(() => useTeamsApi(), { wrapper });

      const body = { name: "renamed" };
      const resp = await result.current.patch<{ updated: boolean }>("/agents/abc", body);

      expect(resp).toEqual({ updated: true });
      expect(mockPut).toHaveBeenCalledWith("/teams/agents/abc", body);
      expect(mockPost).not.toHaveBeenCalled();
    });
  });

  describe("del", () => {
    it("prefixes /teams and forwards to api.del", async () => {
      mockDel.mockResolvedValueOnce({});
      const { result } = renderHook(() => useTeamsApi(), { wrapper });

      await result.current.del("/agents/abc");

      expect(mockDel).toHaveBeenCalledWith("/teams/agents/abc");
    });
  });
});
