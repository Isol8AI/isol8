import { describe, test, expect, beforeEach, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";

import { useInboxKeyboardNav } from "@/components/teams/inbox/hooks/useInboxKeyboardNav";
import type { InboxKeyboardNavEntry } from "@/components/teams/shared/lib/inbox";

const items: InboxKeyboardNavEntry[] = [
  { id: "1", kind: "issue" },
  { id: "2", kind: "issue" },
  { id: "3", kind: "issue" },
];

function makeBaseProps() {
  return {
    enableNav: true,
    enableArchive: true,
    navItems: items,
    selectedIndex: 0,
    onSelectIndex: vi.fn(),
    onOpen: vi.fn(),
    onArchive: vi.fn(),
    onMarkRead: vi.fn(),
    onUndoArchive: vi.fn(),
    hasUndoableArchive: false,
  };
}

function fire(key: string, init: KeyboardEventInit = {}): KeyboardEvent {
  const event = new KeyboardEvent("keydown", {
    key,
    cancelable: true,
    bubbles: true,
    ...init,
  });
  act(() => {
    document.dispatchEvent(event);
  });
  return event;
}

describe("useInboxKeyboardNav", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test("j moves selection down", () => {
    const props = makeBaseProps();
    renderHook(() => useInboxKeyboardNav(props));
    fire("j");
    expect(props.onSelectIndex).toHaveBeenCalledWith(1);
  });

  test("k moves selection up", () => {
    const props = { ...makeBaseProps(), selectedIndex: 1 };
    renderHook(() => useInboxKeyboardNav(props));
    fire("k");
    expect(props.onSelectIndex).toHaveBeenCalledWith(0);
  });

  test("ArrowDown / ArrowUp aliases work", () => {
    const props = makeBaseProps();
    const { rerender } = renderHook((p) => useInboxKeyboardNav(p), {
      initialProps: props,
    });
    fire("ArrowDown");
    expect(props.onSelectIndex).toHaveBeenLastCalledWith(1);
    // Caller would advance selectedIndex; simulate by re-rendering with the
    // new value so ArrowUp computes from index=1.
    rerender({ ...props, selectedIndex: 1 });
    fire("ArrowUp");
    expect(props.onSelectIndex).toHaveBeenLastCalledWith(0);
  });

  test("j clamps at last item", () => {
    const props = { ...makeBaseProps(), selectedIndex: 2 };
    renderHook(() => useInboxKeyboardNav(props));
    fire("j");
    expect(props.onSelectIndex).toHaveBeenLastCalledWith(2); // unchanged (clamped)
  });

  test("k clamps at first item", () => {
    const props = { ...makeBaseProps(), selectedIndex: 0 };
    renderHook(() => useInboxKeyboardNav(props));
    fire("k");
    expect(props.onSelectIndex).toHaveBeenLastCalledWith(0); // unchanged (clamped)
  });

  test("j with selectedIndex < 0 jumps to 0", () => {
    const props = { ...makeBaseProps(), selectedIndex: -1 };
    renderHook(() => useInboxKeyboardNav(props));
    fire("j");
    expect(props.onSelectIndex).toHaveBeenLastCalledWith(0);
  });

  test("j with empty navItems is a no-op", () => {
    const props = { ...makeBaseProps(), navItems: [] };
    renderHook(() => useInboxKeyboardNav(props));
    fire("j");
    expect(props.onSelectIndex).not.toHaveBeenCalled();
  });

  test("Enter calls onOpen with selected item", () => {
    const props = { ...makeBaseProps(), selectedIndex: 1 };
    renderHook(() => useInboxKeyboardNav(props));
    fire("Enter");
    expect(props.onOpen).toHaveBeenCalledWith(items[1]);
  });

  test("Enter is a no-op when nothing is selected", () => {
    const props = { ...makeBaseProps(), selectedIndex: -1 };
    renderHook(() => useInboxKeyboardNav(props));
    fire("Enter");
    expect(props.onOpen).not.toHaveBeenCalled();
  });

  test("a calls onArchive", () => {
    const props = makeBaseProps();
    renderHook(() => useInboxKeyboardNav(props));
    fire("a");
    expect(props.onArchive).toHaveBeenCalledWith(items[0]);
  });

  test("y also calls onArchive", () => {
    const props = makeBaseProps();
    renderHook(() => useInboxKeyboardNav(props));
    fire("y");
    expect(props.onArchive).toHaveBeenCalledWith(items[0]);
  });

  test("r calls onMarkRead", () => {
    const props = makeBaseProps();
    renderHook(() => useInboxKeyboardNav(props));
    fire("r");
    expect(props.onMarkRead).toHaveBeenCalledWith(items[0]);
  });

  test("u calls onUndoArchive when hasUndoableArchive=true", () => {
    const props = { ...makeBaseProps(), hasUndoableArchive: true };
    renderHook(() => useInboxKeyboardNav(props));
    fire("u");
    expect(props.onUndoArchive).toHaveBeenCalledTimes(1);
  });

  test("u does NOTHING when hasUndoableArchive=false", () => {
    const props = { ...makeBaseProps(), hasUndoableArchive: false };
    renderHook(() => useInboxKeyboardNav(props));
    fire("u");
    expect(props.onUndoArchive).not.toHaveBeenCalled();
  });

  test("enableNav=false silences nav keys (j/k/Arrow/Enter)", () => {
    const props = { ...makeBaseProps(), enableNav: false };
    renderHook(() => useInboxKeyboardNav(props));
    fire("j");
    fire("k");
    fire("ArrowDown");
    fire("ArrowUp");
    fire("Enter");
    expect(props.onSelectIndex).not.toHaveBeenCalled();
    expect(props.onOpen).not.toHaveBeenCalled();
  });

  test("enableArchive=false silences archive keys (a/y/r) but j still works", () => {
    const props = {
      ...makeBaseProps(),
      enableArchive: false,
      hasUndoableArchive: true,
    };
    renderHook(() => useInboxKeyboardNav(props));
    fire("a");
    fire("y");
    fire("r");
    fire("u");
    expect(props.onArchive).not.toHaveBeenCalled();
    expect(props.onMarkRead).not.toHaveBeenCalled();
    expect(props.onUndoArchive).not.toHaveBeenCalled();
    // Nav keys still respond when only archive is gated.
    fire("j");
    expect(props.onSelectIndex).toHaveBeenCalledWith(1);
  });

  test("enableNav=true + enableArchive=false: a is silenced but j fires", () => {
    const props = { ...makeBaseProps(), enableArchive: false };
    renderHook(() => useInboxKeyboardNav(props));
    fire("a");
    expect(props.onArchive).not.toHaveBeenCalled();
    fire("j");
    expect(props.onSelectIndex).toHaveBeenCalledWith(1);
  });

  test("typing in an input is ignored", () => {
    const props = makeBaseProps();
    renderHook(() => useInboxKeyboardNav(props));
    const input = document.createElement("input");
    document.body.appendChild(input);
    try {
      const event = new KeyboardEvent("keydown", {
        key: "j",
        cancelable: true,
        bubbles: true,
      });
      Object.defineProperty(event, "target", { value: input });
      act(() => {
        document.dispatchEvent(event);
      });
      expect(props.onSelectIndex).not.toHaveBeenCalled();
    } finally {
      document.body.removeChild(input);
    }
  });

  test("modifier+j is ignored", () => {
    const props = makeBaseProps();
    renderHook(() => useInboxKeyboardNav(props));
    fire("j", { metaKey: true });
    expect(props.onSelectIndex).not.toHaveBeenCalled();
  });

  test("modifier+u is ignored even when hasUndoableArchive=true", () => {
    const props = { ...makeBaseProps(), hasUndoableArchive: true };
    renderHook(() => useInboxKeyboardNav(props));
    fire("u", { metaKey: true });
    expect(props.onUndoArchive).not.toHaveBeenCalled();
  });

  test("hasOpenDialog=true gates everything except undo", () => {
    const props = { ...makeBaseProps(), hasOpenDialog: true };
    renderHook(() => useInboxKeyboardNav(props));
    fire("j");
    fire("a");
    fire("Enter");
    expect(props.onSelectIndex).not.toHaveBeenCalled();
    expect(props.onArchive).not.toHaveBeenCalled();
    expect(props.onOpen).not.toHaveBeenCalled();
  });

  test("hasOpenDialog=true also gates undo (resolver checks it)", () => {
    const props = {
      ...makeBaseProps(),
      hasUndoableArchive: true,
      hasOpenDialog: true,
    };
    renderHook(() => useInboxKeyboardNav(props));
    fire("u");
    expect(props.onUndoArchive).not.toHaveBeenCalled();
  });

  test("listener is cleaned up on unmount", () => {
    const props = makeBaseProps();
    const { unmount } = renderHook(() => useInboxKeyboardNav(props));
    unmount();
    fire("j");
    expect(props.onSelectIndex).not.toHaveBeenCalled();
  });

  test("listener uses latest callbacks across re-renders (ref pattern)", () => {
    const onArchiveV1 = vi.fn();
    const onArchiveV2 = vi.fn();
    const base = makeBaseProps();
    const { rerender } = renderHook(
      (p: ReturnType<typeof makeBaseProps>) => useInboxKeyboardNav(p),
      { initialProps: { ...base, onArchive: onArchiveV1 } },
    );
    rerender({ ...base, onArchive: onArchiveV2 });
    fire("a");
    expect(onArchiveV1).not.toHaveBeenCalled();
    expect(onArchiveV2).toHaveBeenCalledWith(items[0]);
  });

  test("unrelated keys are ignored", () => {
    const props = makeBaseProps();
    renderHook(() => useInboxKeyboardNav(props));
    fire("x");
    fire("z");
    fire("Tab");
    expect(props.onSelectIndex).not.toHaveBeenCalled();
    expect(props.onOpen).not.toHaveBeenCalled();
    expect(props.onArchive).not.toHaveBeenCalled();
    expect(props.onMarkRead).not.toHaveBeenCalled();
  });
});
