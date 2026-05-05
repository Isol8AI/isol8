import { describe, test, expect, vi } from "vitest";
import { renderHook } from "@testing-library/react";

// Mock useTeamsApi BEFORE importing the hook.
vi.mock("@/hooks/useTeamsApi", () => ({
  useTeamsApi: vi.fn(),
}));

import { useInboxData } from "@/components/teams/inbox/hooks/useInboxData";
import { useTeamsApi } from "@/hooks/useTeamsApi";

const mockUseTeamsApi = vi.mocked(useTeamsApi);

function makeRead(
  perPath: Record<string, { data?: unknown; isLoading?: boolean; error?: Error }>
) {
  return vi.fn((path: string) => {
    const r = perPath[path] ?? { data: undefined, isLoading: false, error: null };
    return {
      data: r.data,
      isLoading: r.isLoading ?? false,
      error: r.error ?? null,
      mutate: vi.fn(),
      isValidating: false,
    };
  });
}

describe("useInboxData", () => {
  test("returns empty arrays + loading=false when reads return undefined data", () => {
    mockUseTeamsApi.mockReturnValue({
      read: makeRead({}),
      post: vi.fn(),
      patch: vi.fn(),
      del: vi.fn(),
    } as unknown as ReturnType<typeof useTeamsApi>);

    const { result } = renderHook(() => useInboxData());
    expect(result.current.mineIssues).toEqual([]);
    expect(result.current.touchedIssues).toEqual([]);
    expect(result.current.allIssues).toEqual([]);
    expect(result.current.isLoading).toBe(false);
    expect(result.current.isError).toBe(false);
    expect(result.current.error).toBeNull();
  });

  test("normalizes envelope vs array shape", () => {
    const issue1 = { id: "1", title: "A", status: "todo" };
    const issue2 = { id: "2", title: "B", status: "todo" };

    mockUseTeamsApi.mockReturnValue({
      read: makeRead({
        "/inbox?tab=mine": { data: { items: [issue1] } }, // envelope
        "/inbox?tab=recent": { data: [issue2] }, // bare array
        "/inbox?tab=all": { data: { items: [issue1, issue2] } },
      }),
      post: vi.fn(),
      patch: vi.fn(),
      del: vi.fn(),
    } as unknown as ReturnType<typeof useTeamsApi>);

    const { result } = renderHook(() => useInboxData());
    expect(result.current.mineIssues).toEqual([issue1]);
    expect(result.current.touchedIssues).toEqual([issue2]);
    expect(result.current.allIssues).toEqual([issue1, issue2]);
  });

  test("isLoading true when any read is loading", () => {
    mockUseTeamsApi.mockReturnValue({
      read: makeRead({
        "/inbox?tab=mine": { isLoading: true },
      }),
      post: vi.fn(),
      patch: vi.fn(),
      del: vi.fn(),
    } as unknown as ReturnType<typeof useTeamsApi>);

    const { result } = renderHook(() => useInboxData());
    expect(result.current.isLoading).toBe(true);
  });

  test("isError true when any read has an error; surfaces the first error", () => {
    const err = new Error("boom");
    mockUseTeamsApi.mockReturnValue({
      read: makeRead({
        "/inbox?tab=recent": { error: err },
      }),
      post: vi.fn(),
      patch: vi.fn(),
      del: vi.fn(),
    } as unknown as ReturnType<typeof useTeamsApi>);

    const { result } = renderHook(() => useInboxData());
    expect(result.current.isError).toBe(true);
    expect(result.current.error).toBe(err);
  });

  test("calls read with the queryKeys-derived paths", () => {
    const read = makeRead({});
    mockUseTeamsApi.mockReturnValue({
      read,
      post: vi.fn(),
      patch: vi.fn(),
      del: vi.fn(),
    } as unknown as ReturnType<typeof useTeamsApi>);

    renderHook(() => useInboxData());
    expect(read).toHaveBeenCalledWith("/inbox?tab=mine");
    expect(read).toHaveBeenCalledWith("/inbox?tab=recent");
    expect(read).toHaveBeenCalledWith("/inbox?tab=all");
  });
});
