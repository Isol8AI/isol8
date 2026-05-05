import { describe, test, expect, beforeEach, vi } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";

// Mocks BEFORE imports
vi.mock("@/hooks/useTeamsApi", () => ({ useTeamsApi: vi.fn() }));
vi.mock("swr", async () => {
  const actual = await vi.importActual<typeof import("swr")>("swr");
  return { ...actual, useSWRConfig: vi.fn() };
});

import { useInboxArchiveStack } from "@/components/teams/inbox/hooks/useInboxArchiveStack";
import { useTeamsApi } from "@/hooks/useTeamsApi";
import { useSWRConfig } from "swr";

const mockPost = vi.fn();
const mockMutate = vi.fn();
const mockCacheGet = vi.fn();
const mockCache = {
  get: mockCacheGet,
  set: vi.fn(),
  delete: vi.fn(),
  keys: vi.fn(),
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useTeamsApi).mockReturnValue({
    read: vi.fn(),
    post: mockPost,
    patch: vi.fn(),
    del: vi.fn(),
  } as unknown as ReturnType<typeof useTeamsApi>);
  vi.mocked(useSWRConfig).mockReturnValue({
    cache: mockCache,
    mutate: mockMutate,
  } as unknown as ReturnType<typeof useSWRConfig>);
});

describe("useInboxArchiveStack", () => {
  test("starts empty + hasUndoableArchive=false", () => {
    const { result } = renderHook(() => useInboxArchiveStack());
    expect(result.current.archivingIssueIds.size).toBe(0);
    expect(result.current.hasUndoableArchive).toBe(false);
  });

  test("archive(id) optimistically removes from all 3 inbox keys + posts to BFF", async () => {
    mockPost.mockResolvedValue({ ok: true });
    const { result } = renderHook(() => useInboxArchiveStack());
    await act(async () => {
      await result.current.archive("iss_1");
    });
    expect(mockPost).toHaveBeenCalledWith("/inbox/iss_1/archive", {});
    // 3 optimistic mutates + 3 settle revalidates = 6 calls
    expect(mockMutate).toHaveBeenCalledTimes(6);
  });

  test("archive succeeds → pushes onto undo stack", async () => {
    mockPost.mockResolvedValue({});
    const { result } = renderHook(() => useInboxArchiveStack());
    await act(async () => {
      await result.current.archive("iss_1");
    });
    expect(result.current.hasUndoableArchive).toBe(true);
  });

  test("archive errors → rollback + does NOT add to undo stack", async () => {
    mockCacheGet.mockReturnValue({
      data: { items: [{ id: "iss_1", title: "x", status: "todo" }] },
    });
    mockPost.mockRejectedValue(new Error("server boom"));
    const { result } = renderHook(() => useInboxArchiveStack());
    await act(async () => {
      await expect(result.current.archive("iss_1")).rejects.toThrow(
        "server boom",
      );
    });
    expect(result.current.hasUndoableArchive).toBe(false);
  });

  test("archivingIssueIds tracks in-flight ids during await", async () => {
    let resolvePost: (v: unknown) => void = () => {};
    mockPost.mockImplementation(
      () =>
        new Promise((res) => {
          resolvePost = res;
        }),
    );
    const { result } = renderHook(() => useInboxArchiveStack());
    let archivePromise: Promise<void>;
    act(() => {
      archivePromise = result.current.archive("iss_1");
    });
    await waitFor(() =>
      expect(result.current.archivingIssueIds.has("iss_1")).toBe(true),
    );
    await act(async () => {
      resolvePost({});
      await archivePromise!;
    });
    expect(result.current.archivingIssueIds.has("iss_1")).toBe(false);
  });

  test("undoArchive pops from stack + posts unarchive (LIFO)", async () => {
    mockPost.mockResolvedValue({});
    const { result } = renderHook(() => useInboxArchiveStack());
    await act(async () => {
      await result.current.archive("iss_1");
    });
    await act(async () => {
      await result.current.archive("iss_2");
    });
    expect(result.current.hasUndoableArchive).toBe(true);

    mockPost.mockClear();
    await act(async () => {
      await result.current.undoArchive();
    });
    // Most recent (iss_2) is undone first
    expect(mockPost).toHaveBeenCalledWith("/inbox/iss_2/unarchive", {});
  });

  test("undoArchive on empty stack is a no-op", async () => {
    const { result } = renderHook(() => useInboxArchiveStack());
    await act(async () => {
      await result.current.undoArchive();
    });
    expect(mockPost).not.toHaveBeenCalled();
  });

  test("undoArchive failure restores the popped id to the stack", async () => {
    mockPost.mockResolvedValueOnce({}); // archive succeeds
    const { result } = renderHook(() => useInboxArchiveStack());
    await act(async () => {
      await result.current.archive("iss_1");
    });
    expect(result.current.hasUndoableArchive).toBe(true);

    mockPost.mockRejectedValueOnce(new Error("unarchive failed"));
    await act(async () => {
      await expect(result.current.undoArchive()).rejects.toThrow(
        "unarchive failed",
      );
    });
    expect(result.current.hasUndoableArchive).toBe(true); // restored
  });

  test("markRead posts + revalidates", async () => {
    mockPost.mockResolvedValue({});
    const { result } = renderHook(() => useInboxArchiveStack());
    await act(async () => {
      await result.current.markRead("iss_1");
    });
    expect(mockPost).toHaveBeenCalledWith("/inbox/iss_1/mark-read", {});
    expect(mockMutate).toHaveBeenCalledTimes(3); // 3 inbox keys
  });

  test("markUnread posts + revalidates", async () => {
    mockPost.mockResolvedValue({});
    const { result } = renderHook(() => useInboxArchiveStack());
    await act(async () => {
      await result.current.markUnread("iss_1");
    });
    expect(mockPost).toHaveBeenCalledWith("/inbox/iss_1/mark-unread", {});
    expect(mockMutate).toHaveBeenCalledTimes(3);
  });
});
