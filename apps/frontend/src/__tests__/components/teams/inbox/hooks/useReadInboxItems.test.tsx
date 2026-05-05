import {
  describe,
  test,
  expect,
  beforeAll,
  beforeEach,
  afterEach,
  vi,
} from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useReadInboxItems } from "@/components/teams/inbox/hooks/useReadInboxItems";

// Node 22+ ships a built-in `localStorage` that requires `--localstorage-file`
// to actually function. In our vitest+jsdom setup it shadows jsdom's
// localStorage and exposes a stub that throws on `.clear()` / `.setItem()`.
// Install a Map-backed polyfill on both `globalThis` and `Storage.prototype`
// so production code (which calls `localStorage.{getItem,setItem,...}`) and
// tests (which `vi.spyOn(Storage.prototype, ...)`) both work.
beforeAll(() => {
  const store = new Map<string, string>();
  const polyfill: Storage = {
    getItem: (k) => (store.has(k) ? (store.get(k) as string) : null),
    setItem: (k, v) => {
      store.set(k, String(v));
    },
    removeItem: (k) => {
      store.delete(k);
    },
    clear: () => {
      store.clear();
    },
    key: (i) => Array.from(store.keys())[i] ?? null,
    get length() {
      return store.size;
    },
  };
  Object.defineProperty(globalThis, "localStorage", {
    value: polyfill,
    writable: true,
    configurable: true,
  });
  if (typeof window !== "undefined") {
    Object.defineProperty(window, "localStorage", {
      value: polyfill,
      writable: true,
      configurable: true,
    });
  }
  Storage.prototype.getItem = function (k: string) {
    return polyfill.getItem(k);
  };
  Storage.prototype.setItem = function (k: string, v: string) {
    polyfill.setItem(k, v);
  };
  Storage.prototype.removeItem = function (k: string) {
    polyfill.removeItem(k);
  };
  Storage.prototype.clear = function () {
    polyfill.clear();
  };
});

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useReadInboxItems", () => {
  test("returns empty set when companyId is null", () => {
    const { result } = renderHook(() => useReadInboxItems(null));
    expect(result.current.readItemKeys).toBeInstanceOf(Set);
    expect(result.current.readItemKeys.size).toBe(0);
  });

  test("null companyId mutators are no-ops", () => {
    const { result } = renderHook(() => useReadInboxItems(null));
    act(() => {
      result.current.markRead("iss_1");
      result.current.markUnread("iss_1");
      result.current.markManyRead(["iss_1", "iss_2"]);
      result.current.clearAll();
    });
    expect(result.current.readItemKeys.size).toBe(0);
    // Nothing persisted under any key.
    expect(localStorage.length).toBe(0);
  });

  test("loads initial state from localStorage", () => {
    localStorage.setItem(
      "paperclip:inbox:co_1:read-items",
      JSON.stringify(["iss_1", "iss_2"]),
    );
    const { result } = renderHook(() => useReadInboxItems("co_1"));
    expect(result.current.isRead("iss_1")).toBe(true);
    expect(result.current.isRead("iss_2")).toBe(true);
    expect(result.current.isRead("iss_3")).toBe(false);
    expect(result.current.readItemKeys.size).toBe(2);
  });

  test("markRead adds to set + persists", () => {
    const { result } = renderHook(() => useReadInboxItems("co_1"));
    act(() => result.current.markRead("iss_1"));
    expect(result.current.isRead("iss_1")).toBe(true);
    const raw = localStorage.getItem("paperclip:inbox:co_1:read-items");
    expect(raw).not.toBeNull();
    expect(JSON.parse(raw as string)).toEqual(["iss_1"]);
  });

  test("markRead is idempotent — calling twice does not duplicate", () => {
    const { result } = renderHook(() => useReadInboxItems("co_1"));
    act(() => result.current.markRead("iss_1"));
    act(() => result.current.markRead("iss_1"));
    expect(result.current.readItemKeys.size).toBe(1);
  });

  test("markUnread removes from set + persists", () => {
    localStorage.setItem(
      "paperclip:inbox:co_1:read-items",
      JSON.stringify(["iss_1", "iss_2"]),
    );
    const { result } = renderHook(() => useReadInboxItems("co_1"));
    act(() => result.current.markUnread("iss_1"));
    expect(result.current.isRead("iss_1")).toBe(false);
    expect(result.current.isRead("iss_2")).toBe(true);
    const raw = localStorage.getItem("paperclip:inbox:co_1:read-items");
    expect(JSON.parse(raw as string)).toEqual(["iss_2"]);
  });

  test("markUnread on absent id is a no-op", () => {
    const { result } = renderHook(() => useReadInboxItems("co_1"));
    const before = result.current.readItemKeys;
    act(() => result.current.markUnread("iss_x"));
    // Same Set instance — no spurious re-render churn.
    expect(result.current.readItemKeys).toBe(before);
  });

  test("markManyRead is single update + single save", () => {
    // Wrap localStorage.setItem directly — production code calls
    // `localStorage.setItem(...)` which hits the polyfill object, not
    // Storage.prototype, so spying on the prototype wouldn't observe it.
    const original = localStorage.setItem.bind(localStorage);
    const writes: Array<[string, string]> = [];
    localStorage.setItem = (k: string, v: string) => {
      writes.push([k, v]);
      original(k, v);
    };
    try {
      const { result } = renderHook(() => useReadInboxItems("co_1"));
      writes.length = 0; // ignore any setItem from initial render
      act(() => result.current.markManyRead(["iss_1", "iss_2", "iss_3"]));
      expect(result.current.readItemKeys.size).toBe(3);
      expect(result.current.isRead("iss_1")).toBe(true);
      expect(result.current.isRead("iss_2")).toBe(true);
      expect(result.current.isRead("iss_3")).toBe(true);
      const readItemWrites = writes.filter(
        ([k]) => k === "paperclip:inbox:co_1:read-items",
      );
      expect(readItemWrites.length).toBe(1);
      // And the single write contains all three ids.
      expect(JSON.parse(readItemWrites[0][1])).toEqual(
        expect.arrayContaining(["iss_1", "iss_2", "iss_3"]),
      );
    } finally {
      localStorage.setItem = original;
    }
  });

  test("markManyRead with all already-read ids is a no-op", () => {
    localStorage.setItem(
      "paperclip:inbox:co_1:read-items",
      JSON.stringify(["iss_1", "iss_2"]),
    );
    const { result } = renderHook(() => useReadInboxItems("co_1"));
    const before = result.current.readItemKeys;
    act(() => result.current.markManyRead(["iss_1", "iss_2"]));
    expect(result.current.readItemKeys).toBe(before);
  });

  test("clearAll empties + persists", () => {
    localStorage.setItem(
      "paperclip:inbox:co_1:read-items",
      JSON.stringify(["iss_1", "iss_2"]),
    );
    const { result } = renderHook(() => useReadInboxItems("co_1"));
    expect(result.current.readItemKeys.size).toBe(2);
    act(() => result.current.clearAll());
    expect(result.current.readItemKeys.size).toBe(0);
    const raw = localStorage.getItem("paperclip:inbox:co_1:read-items");
    expect(JSON.parse(raw as string)).toEqual([]);
  });

  test("clearAll on already-empty set is a no-op", () => {
    const { result } = renderHook(() => useReadInboxItems("co_1"));
    const before = result.current.readItemKeys;
    act(() => result.current.clearAll());
    expect(result.current.readItemKeys).toBe(before);
  });

  test("storage event from another tab updates state", () => {
    const { result } = renderHook(() => useReadInboxItems("co_1"));
    expect(result.current.isRead("iss_x")).toBe(false);
    act(() => {
      // Simulate another tab writing then dispatching the storage event.
      localStorage.setItem(
        "paperclip:inbox:co_1:read-items",
        JSON.stringify(["iss_x"]),
      );
      const event = new StorageEvent("storage", {
        key: "paperclip:inbox:co_1:read-items",
      });
      window.dispatchEvent(event);
    });
    expect(result.current.isRead("iss_x")).toBe(true);
  });

  test("storage event for unrelated key is ignored", () => {
    const { result } = renderHook(() => useReadInboxItems("co_1"));
    act(() => {
      const event = new StorageEvent("storage", { key: "unrelated" });
      window.dispatchEvent(event);
    });
    expect(result.current.readItemKeys.size).toBe(0);
  });

  test("storage event for a different company's key is ignored", () => {
    const { result } = renderHook(() => useReadInboxItems("co_1"));
    act(() => {
      localStorage.setItem(
        "paperclip:inbox:co_2:read-items",
        JSON.stringify(["iss_x"]),
      );
      const event = new StorageEvent("storage", {
        key: "paperclip:inbox:co_2:read-items",
      });
      window.dispatchEvent(event);
    });
    expect(result.current.readItemKeys.size).toBe(0);
  });

  test("changing companyId reloads state", () => {
    localStorage.setItem(
      "paperclip:inbox:co_1:read-items",
      JSON.stringify(["a"]),
    );
    localStorage.setItem(
      "paperclip:inbox:co_2:read-items",
      JSON.stringify(["b"]),
    );
    const { result, rerender } = renderHook(
      ({ id }: { id: string | null }) => useReadInboxItems(id),
      { initialProps: { id: "co_1" as string | null } },
    );
    expect(result.current.isRead("a")).toBe(true);
    expect(result.current.isRead("b")).toBe(false);
    rerender({ id: "co_2" });
    expect(result.current.isRead("a")).toBe(false);
    expect(result.current.isRead("b")).toBe(true);
  });

  test("transitioning companyId from null to id loads stored state", () => {
    localStorage.setItem(
      "paperclip:inbox:co_1:read-items",
      JSON.stringify(["iss_1"]),
    );
    const { result, rerender } = renderHook(
      ({ id }: { id: string | null }) => useReadInboxItems(id),
      { initialProps: { id: null as string | null } },
    );
    expect(result.current.readItemKeys.size).toBe(0);
    rerender({ id: "co_1" });
    expect(result.current.isRead("iss_1")).toBe(true);
  });
});
