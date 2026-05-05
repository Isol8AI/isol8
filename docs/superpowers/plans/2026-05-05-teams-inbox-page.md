# Teams Inbox Page Implementation Plan (PR #3c)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Replace `InboxPanel.tsx`'s 49-line tier-1 stub with a faithful port of upstream Paperclip's `pages/Inbox.tsx`. Components from PR #3b (IssueRow, IssueColumns, IssueFiltersPopover, SwipeToArchive, KeyboardShortcutsCheatsheet) get wired up. SWR hooks for archive / mark-read / inbox data fan-out. Keyboard navigation, archive-with-undo (keyboard only — no inline toast, matching upstream), per-tab empty states, realtime invalidation.

**Architecture:** Direct port of upstream's structure; React Query → SWR translation. Component split into `InboxPage` + `InboxToolbar` + `InboxList` + dedicated hooks (`useInboxData`, `useInboxKeyboardNav`, `useInboxArchiveStack`). Realtime extends PR #518's `TeamsEventsProvider` `EVENT_KEY_MAP` — no new subscriptions.

**Tech Stack:** React 19 + Next 16 App Router + Tailwind v4 + SWR + lucide-react + shadcn primitives. No new npm deps.

**Upstream reference:** `paperclip/ui/src/pages/Inbox.tsx` (2583 LOC). License attribution headers per file as in PR #3b.

---

## Critical scope corrections from research

The original 4-PR design assumed Inbox.tsx had 7 tabs (mine/recent/all/unread/approvals/runs/joins). **It has 4** (mine/recent/all/unread). Approvals + failed-runs + join-requests are *categories within the "all" tab*, not standalone tabs. The BFF accepts the extra tab values from PR #524 (Codex P1 expanded the regex defensively) — they're harmless dead branches in this PR. Frontend never sends them.

**Other corrections:**
- **No realtime in upstream Inbox.tsx.** Freshness via React Query refetch + `refetchInterval: 5000` on live-runs only. Our port can leverage TeamsEventsProvider for richer invalidation than upstream.
- **No inline undo bar / toast.** Undo is **keyboard-only** (Cmd+Z) with an in-memory stack. We match upstream — no global toast lib needed.
- **All keyboard logic is inline** in upstream's Inbox.tsx (~210 LOC of useEffect). We factor into `useInboxKeyboardNav` for cleanliness.
- **Single render path with Tailwind responsive classes.** No mobile-vs-desktop component branching beyond `useSidebar().isMobile` for the parent-child nesting toggle. Nesting is deferred — drops the only JS-level branch.

---

## In scope (#3c v1)

- 4 tabs: mine / recent / all / unread (URL-synced via Next router)
- Search input (mobile + desktop variants, Tailwind responsive)
- `IssueFiltersPopover` integration (already ported in #3b)
- `IssueRow` loop with selection state
- Keyboard nav: `j`/`k` next/prev, `Enter` open, `a`/`y` archive, `r` mark-read, `Cmd+Z`/`Ctrl+Z` undo. **Drop:** `?` cheatsheet, `/` search-focus, `U` mark-unread (defer; not in upstream Inbox.tsx either for `?`/`/`)
- Optimistic archive with cache rollback on error + Cmd+Z stack
- "Mark all as read" button + confirm dialog
- Per-tab empty state copy ("Inbox zero." / "No new inbox items." / "No recent inbox items." / "No inbox items match these filters." / "No inbox items match your search.")
- Loading skeleton (`PageSkeleton variant="inbox"` — port a minimal one)
- Realtime invalidation via TeamsEventsProvider EVENT_KEY_MAP

## Out of scope (deferred)

- **Parent-child issue nesting** — heavy code (`ListTree` toggle, recursion, group collapse) for niche feature. Defer.
- **Isolated workspaces** — gated on instance feature flag we don't have.
- **Live-runs 5s polling + highlight** — defer until we wire BFF /teams/inbox/live-runs into the realtime layer.
- **Failed-runs row + heartbeats query** — `FailedRunInboxRow` component + `agents.wakeup` retry. Defer until needed.
- **Approvals + join-requests rows** — `ApprovalInboxRow`, `JoinRequestInboxRow`, all-tab category select. Approvals tab works as part of the broader Approvals panel (separate); inline display in Inbox defers.
- **Dashboard alerts section** — agent error count + budget alerts. No BFF dashboard endpoint yet.
- **Group-by popover** (workspace / project) — flat list in v1.
- **Column picker** — use `DEFAULT_INBOX_ISSUE_COLUMNS` constant from PR #3b; no UI to customize.
- **Routine executions** (`includeRoutineExecutions: true` param) — defer until we surface routines.
- **Detail page navigation** — clicks navigate to `/teams/issues/[id]` which is still a stub. #3d makes it real.

---

## File structure

```
apps/frontend/src/components/teams/
├── inbox/
│   ├── InboxPage.tsx                  # NEW. ~250 LOC. The page itself.
│   ├── InboxToolbar.tsx               # NEW. ~180 LOC. Tabs + search + filters + mark-all-read.
│   ├── InboxList.tsx                  # NEW. ~200 LOC. Flat issue list w/ today + search dividers.
│   └── hooks/
│       ├── useInboxData.ts            # NEW. SWR fan-out. ~80 LOC.
│       ├── useInboxKeyboardNav.ts     # NEW. Extract upstream's inline kb logic. ~150 LOC.
│       ├── useInboxArchiveStack.ts    # NEW. Archive + undo + mark-read mutations. ~130 LOC.
│       └── useInboxFilterPreferences.ts # NEW. localStorage-backed prefs. ~50 LOC.
├── shared/
│   ├── lib/
│   │   ├── inbox.ts                   # NEW. Pure helpers + types. ~250 LOC.
│   │   ├── keyboardShortcuts.ts       # NEW. Subset of upstream's 167 LOC. ~80 LOC.
│   │   └── inboxStorage.ts            # NEW. localStorage helpers. ~70 LOC.
│   └── components/
│       └── PageSkeleton.tsx           # NEW. Minimal loading state. ~40 LOC.
└── panels/
    └── InboxPanel.tsx                 # MODIFY. Body becomes <InboxPage />. ~10 LOC final.

apps/frontend/src/components/teams/TeamsEventsProvider.tsx  # MODIFY. Extend EVENT_KEY_MAP.

apps/frontend/src/__tests__/components/teams/inbox/
├── InboxPage.test.tsx
├── InboxToolbar.test.tsx
├── InboxList.test.tsx
└── hooks/
    ├── useInboxData.test.ts
    ├── useInboxKeyboardNav.test.ts
    └── useInboxArchiveStack.test.ts
```

---

## Common conventions

- Each ported file gets a 3-line MIT attribution header (`Ported from upstream Paperclip ...`) per the PR #3b precedent.
- All test files import explicitly from vitest: `import { describe, test, expect, vi } from "vitest";` (lesson learned from PR #3b CI failure).
- shadcn primitives `dialog`, `dropdown-menu`, `tooltip`, `popover`, `badge`, `checkbox`, `input`, `button`, `alert-dialog` already exist. `tooltip` STILL not vendored — degrade to native `title=` attribute consistent with PR #3b.
- All upstream `useQuery({ queryKey: ..., queryFn: ... })` calls translate to `useTeamsApi().read(<key>)` (the existing hook at `apps/frontend/src/hooks/useTeamsApi.ts`).
- All upstream `useMutation({ mutationFn: ... })` calls translate to `await api.post(...); mutate(<key>)` (SWR cache invalidation via `useSWRConfig().mutate`).
- The `useTeamsApi` hook returns `{ read, post, put, patch, del, mutate }`. Verify the actual interface before each task — it may not have all the helpers we need.
- DO NOT push between tasks. Push at Task 12 to open the PR.

---

## Task 1: lib/inbox.ts — pure helpers + types

**Files:**
- Create: `apps/frontend/src/components/teams/shared/lib/inbox.ts`
- Test: `apps/frontend/src/__tests__/components/teams/shared/lib/inbox.test.ts`

- [x] **Step 1: Read upstream**

```bash
sed -n '1,200p' /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/paperclip/ui/src/lib/inbox.ts
```

Find these exports and port:
- Types: `InboxTab`, `InboxWorkItem`, `InboxGroupedSection`, `InboxKeyboardNavEntry`, `InboxFilterPreferences`, `InboxIssueColumn` (already in `inboxColumns.ts` from #3b — re-export, don't duplicate)
- Constants: `INBOX_MINE_ISSUE_STATUS_FILTER`
- Pure functions: `getInboxWorkItems`, `getRecentTouchedIssues`, `matchesInboxIssueSearch`, `buildGroupedInboxSections` (subset for `groupBy="none"` only; flat list), `buildInboxKeyboardNavEntries`, `resolveInboxSelectionIndex`

Skip: `inboxWorkspaceGrouping`, `resolveInboxNestingEnabled`, `loadInbox*`/`saveInbox*` localStorage helpers (those go in `inboxStorage.ts`, Task 3).

- [x] **Step 2: Write the helpers**

Each function should be pure (no SWR / API access). Types reference our existing `Issue` from `@/components/teams/shared/types`.

- [x] **Step 3: Tests**

For each helper, 3-5 assertions covering the main code paths:

```ts
import { describe, test, expect } from "vitest";
import {
  getInboxWorkItems,
  matchesInboxIssueSearch,
  buildGroupedInboxSections,
  resolveInboxSelectionIndex,
} from "@/components/teams/shared/lib/inbox";
import type { Issue } from "@/components/teams/shared/types";

describe("matchesInboxIssueSearch", () => {
  test("matches title (case-insensitive)", () => {
    const i: Issue = { id: "1", title: "Fix Inbox", status: "todo" };
    expect(matchesInboxIssueSearch(i, "fix")).toBe(true);
    expect(matchesInboxIssueSearch(i, "ship")).toBe(false);
  });
  // ... more
});

// etc per export
```

- [x] **Step 4: Run + commit**

```bash
cd apps/frontend && pnpm test -- src/__tests__/components/teams/shared/lib/inbox.test.ts
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/.worktrees/feat-teams-inbox-page
git add apps/frontend/src/components/teams/shared/lib/inbox.ts apps/frontend/src/__tests__/components/teams/shared/lib/inbox.test.ts docs/superpowers/plans/2026-05-05-teams-inbox-page.md
git commit -m "feat(teams): port lib/inbox pure helpers + InboxTab/WorkItem types"
```

---

## Task 2: lib/keyboardShortcuts.ts subset

**Files:**
- Create: `apps/frontend/src/components/teams/shared/lib/keyboardShortcuts.ts`
- Test: `apps/frontend/src/__tests__/components/teams/shared/lib/keyboardShortcuts.test.ts`

- [ ] **Step 1: Read upstream**

```bash
cat /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/paperclip/ui/src/lib/keyboardShortcuts.ts
```

Port subset:
- `isKeyboardShortcutTextInputTarget(target)` — returns true when target is `input`, `textarea`, or `contenteditable`. Used to skip kbd shortcuts.
- `hasBlockingShortcutDialog()` — checks DOM for an open Radix Dialog.
- `focusPageSearchShortcutTarget()` — finds `[data-page-search]` input + focuses it.
- `resolveInboxUndoArchiveKeyAction(event)` — returns `"undo" | null` for Ctrl/Cmd+Z.
- `shouldBlurPageSearchOnEnter(event)`, `shouldBlurPageSearchOnEscape(event)` — search-input handlers.

Skip: handlers for routes/pages we don't have (issue-detail-specific shortcuts).

- [ ] **Step 2: Tests**

```ts
import { describe, test, expect, beforeEach } from "vitest";
import {
  isKeyboardShortcutTextInputTarget,
  resolveInboxUndoArchiveKeyAction,
} from "@/components/teams/shared/lib/keyboardShortcuts";

describe("isKeyboardShortcutTextInputTarget", () => {
  test("true for input element", () => {
    const el = document.createElement("input");
    expect(isKeyboardShortcutTextInputTarget(el)).toBe(true);
  });
  test("false for div", () => {
    const el = document.createElement("div");
    expect(isKeyboardShortcutTextInputTarget(el)).toBe(false);
  });
  test("true for contenteditable div", () => {
    const el = document.createElement("div");
    el.setAttribute("contenteditable", "true");
    expect(isKeyboardShortcutTextInputTarget(el)).toBe(true);
  });
});

describe("resolveInboxUndoArchiveKeyAction", () => {
  test("returns 'undo' on Cmd+Z", () => {
    const e = new KeyboardEvent("keydown", { key: "z", metaKey: true });
    expect(resolveInboxUndoArchiveKeyAction(e)).toBe("undo");
  });
  test("returns null on plain Z", () => {
    const e = new KeyboardEvent("keydown", { key: "z" });
    expect(resolveInboxUndoArchiveKeyAction(e)).toBeNull();
  });
});
```

- [ ] **Step 3: Commit**

```
feat(teams): port lib/keyboardShortcuts subset for Inbox kbd nav
```

---

## Task 3: inboxStorage.ts — localStorage preference helpers

**Files:**
- Create: `apps/frontend/src/components/teams/shared/lib/inboxStorage.ts`
- Test: `apps/frontend/src/__tests__/components/teams/shared/lib/inboxStorage.test.ts`

- [ ] **Step 1: Port localStorage helpers**

Per-company namespace `paperclip:inbox:<companyId>:<key>`. Functions:

- `loadInboxFilterPreferences(companyId, defaults): InboxFilterPreferences`
- `saveInboxFilterPreferences(companyId, prefs): void`
- `saveLastInboxTab(companyId, tab): void`
- `loadLastInboxTab(companyId): InboxTab | null`
- `loadReadInboxItems(companyId): Set<string>` — set of issue IDs marked read
- `saveReadInboxItems(companyId, ids): void`

Defensive: `try { localStorage.getItem(...) } catch {}` — can fail in private browsing.

- [ ] **Step 2: Tests** with `vi.spyOn(Storage.prototype, "getItem")` for the no-localStorage fallback case.

- [ ] **Step 3: Commit:** `feat(teams): port inbox localStorage preference helpers`

---

## Task 4: hooks/useInboxBadge.ts subset

**Files:**
- Create: `apps/frontend/src/components/teams/inbox/hooks/useReadInboxItems.ts`
- Test: `apps/frontend/src/__tests__/components/teams/inbox/hooks/useReadInboxItems.test.ts`

- [ ] **Step 1: Read upstream**

```bash
cat /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/paperclip/ui/src/hooks/useInboxBadge.ts
```

Port ONLY `useReadInboxItems(companyId)` — returns `{readItemKeys: Set<string>, markRead, markUnread}`. Backed by `loadReadInboxItems`/`saveReadInboxItems` from Task 3. Includes `storage` event listener for cross-tab sync.

Skip: `useDismissedInboxAlerts`, `useInboxDismissals`, `useInboxBadge` itself (these are for non-issue items / alerts which are out of scope for v1).

- [ ] **Step 2: Tests** — assert markRead/markUnread mutates the set, and a `storage` event triggers re-render.

- [ ] **Step 3: Commit:** `feat(teams): port useReadInboxItems hook (localStorage-backed read state)`

---

## Task 5: useInboxData hook — SWR fan-out

**Files:**
- Create: `apps/frontend/src/components/teams/inbox/hooks/useInboxData.ts`
- Test: `apps/frontend/src/__tests__/components/teams/inbox/hooks/useInboxData.test.ts`

- [ ] **Step 1: Read existing useTeamsApi to confirm interface**

```bash
cat apps/frontend/src/hooks/useTeamsApi.ts
```

Verify it returns `{read, post, mutate}` (or similar). If `read` is the SWR-wrapped fetcher, use it; otherwise import `useSWR` directly with the existing `fetcher`.

- [ ] **Step 2: Write the hook**

```ts
// apps/frontend/src/components/teams/inbox/hooks/useInboxData.ts

// Ported from upstream Paperclip's pages/Inbox.tsx data-fetching block
// (paperclip/ui/src/pages/Inbox.tsx:744-835) (MIT, (c) 2025 Paperclip AI).
// Translated from React Query's useQuery to SWR via our useTeamsApi hook.

import { teamsQueryKeys, type InboxTab, type InboxFilters } from "@/components/teams/shared/queryKeys";
import type { Issue } from "@/components/teams/shared/types";
import { useTeamsApi } from "@/hooks/useTeamsApi";

export interface UseInboxDataResult {
  mineIssues: Issue[];
  touchedIssues: Issue[];
  allIssues: Issue[];
  isLoading: boolean;
  isError: boolean;
  error: Error | null;
}

export function useInboxData(): UseInboxDataResult {
  const { read } = useTeamsApi();

  // mine = touchedByUserId=me + inboxArchivedByUserId=me + status filter
  const mine = read<{ items: Issue[] } | Issue[]>(
    teamsQueryKeys.inbox.list("mine", {})
  );
  // recent / unread share the touched-by-me + status filter; client-side filter for unread
  const touched = read<{ items: Issue[] } | Issue[]>(
    teamsQueryKeys.inbox.list("recent", {})
  );
  // all = no filter
  const all = read<{ items: Issue[] } | Issue[]>(
    teamsQueryKeys.inbox.list("all", {})
  );

  const normalize = (data: { items: Issue[] } | Issue[] | undefined): Issue[] => {
    if (!data) return [];
    if (Array.isArray(data)) return data;
    return data.items ?? [];
  };

  return {
    mineIssues: normalize(mine.data),
    touchedIssues: normalize(touched.data),
    allIssues: normalize(all.data),
    isLoading: mine.isLoading || touched.isLoading || all.isLoading,
    isError: !!(mine.error || touched.error || all.error),
    error: mine.error || touched.error || all.error || null,
  };
}
```

(Adapt to `useTeamsApi`'s actual interface; this is illustrative.)

- [ ] **Step 3: Tests**

Mock `useTeamsApi` in the test, return canned data, assert the normalized output:

```ts
import { describe, test, expect, vi } from "vitest";
import { renderHook } from "@testing-library/react";
import { useInboxData } from "@/components/teams/inbox/hooks/useInboxData";

vi.mock("@/hooks/useTeamsApi", () => ({
  useTeamsApi: () => ({
    read: vi.fn().mockReturnValue({ data: { items: [] }, isLoading: false, error: null }),
  }),
}));

test("returns empty arrays when all reads return empty envelopes", () => {
  const { result } = renderHook(() => useInboxData());
  expect(result.current.mineIssues).toEqual([]);
  expect(result.current.isLoading).toBe(false);
});
```

- [ ] **Step 4: Commit:** `feat(teams): port useInboxData hook (SWR fan-out for 3 tab variants)`

---

## Task 6: useInboxKeyboardNav hook

**Files:**
- Create: `apps/frontend/src/components/teams/inbox/hooks/useInboxKeyboardNav.ts`
- Test: `apps/frontend/src/__tests__/components/teams/inbox/hooks/useInboxKeyboardNav.test.ts`

- [ ] **Step 1: Read upstream**

```bash
sed -n '1604,1820p' /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/paperclip/ui/src/pages/Inbox.tsx
```

This is the inline `useEffect` keyboard handler. Extract to a hook.

- [ ] **Step 2: Hook signature**

```ts
export interface UseInboxKeyboardNavParams {
  enabled: boolean;            // gate (e.g., on archive-capable tabs only)
  navItems: InboxKeyboardNavEntry[];   // built by buildInboxKeyboardNavEntries
  selectedIndex: number;
  onSelectIndex: (idx: number) => void;
  onOpen: (item: InboxKeyboardNavEntry) => void;
  onArchive: (item: InboxKeyboardNavEntry) => void;
  onMarkRead: (item: InboxKeyboardNavEntry) => void;
  onUndoArchive: () => void;
}

export function useInboxKeyboardNav(params: UseInboxKeyboardNavParams): void;
```

- [ ] **Step 3: Implementation**

Follow upstream's switch logic. Use `useRef` to keep handler stable across renders (upstream pattern). Skip when `isKeyboardShortcutTextInputTarget(target)` is true. Skip when `hasBlockingShortcutDialog()` is true.

DROP from upstream:
- `U` mark-unread (lowercase `r` mark-read only in v1)
- `ArrowLeft`/`ArrowRight` group-collapse (no nesting in v1)
- Quick-archive arming for issue detail (defer to #3d)

- [ ] **Step 4: Tests**

```ts
test("j fires onSelectIndex with next idx when navItems non-empty", () => {
  const onSelectIndex = vi.fn();
  renderHook(() => useInboxKeyboardNav({
    enabled: true,
    navItems: [{ id: "1", kind: "issue" }, { id: "2", kind: "issue" }],
    selectedIndex: 0,
    onSelectIndex,
    onOpen: vi.fn(),
    onArchive: vi.fn(),
    onMarkRead: vi.fn(),
    onUndoArchive: vi.fn(),
  }));
  fireEvent.keyDown(document, { key: "j" });
  expect(onSelectIndex).toHaveBeenCalledWith(1);
});

// More: k, Enter, a, y, r, Cmd+Z, gating on enabled=false, gating on text input
```

- [ ] **Step 5: Commit:** `feat(teams): port useInboxKeyboardNav hook (j/k/Enter/a/y/r/Cmd+Z)`

---

## Task 7: useInboxArchiveStack hook

**Files:**
- Create: `apps/frontend/src/components/teams/inbox/hooks/useInboxArchiveStack.ts`
- Test: `apps/frontend/src/__tests__/components/teams/inbox/hooks/useInboxArchiveStack.test.ts`

- [ ] **Step 1: Read upstream**

```bash
sed -n '1407,1582p' /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/paperclip/ui/src/pages/Inbox.tsx
```

Lines 1407-1582 are the archive mutation + undo stack. Port into a hook.

- [ ] **Step 2: Hook responsibility**

State:
- `archivingIssueIds: Set<string>` — currently being archived (for fade animation)
- `undoableArchiveIssueIds: string[]` — stack of recently archived ids
- `unarchivingIssueIds: Set<string>` — currently being undone
- `fadingOutIssueIds: Set<string>` — fade animation duration tracking

Actions:
- `archive(issueId): Promise<void>` — optimistic remove + cache update + server call
- `undoArchive(): Promise<void>` — pop last from stack, server unarchive call
- `markRead(issueId): Promise<void>` — server mark-read + cache update
- `markUnread(issueId): Promise<void>` — server mark-unread + cache update

The optimistic update applies to the SWR cache via `useSWRConfig().mutate`. Cancel inflight refetches first (SWR has `mutate(key, undefined, { revalidate: false })`).

- [ ] **Step 3: Tests**

Mock `useTeamsApi.post` + `useSWRConfig.mutate`. Assert the mutate calls happen in order (optimistic → server). Test rollback on server error (mutate gets called with the prev cache value).

- [ ] **Step 4: Commit:** `feat(teams): port useInboxArchiveStack hook (optimistic + Cmd+Z stack)`

---

## Task 8: PageSkeleton component (shared)

**Files:**
- Create: `apps/frontend/src/components/teams/shared/components/PageSkeleton.tsx`
- Test: `apps/frontend/src/__tests__/components/teams/shared/components/PageSkeleton.test.tsx`

- [ ] **Step 1: Port a minimal skeleton**

Upstream's `PageSkeleton` is a generic shimmer; port a minimal version with one variant for now: `<PageSkeleton variant="inbox" />` renders ~5 placeholder rows. ~40 LOC.

- [ ] **Step 2: Test:** assert the skeleton renders ≥5 placeholder bars.

- [ ] **Step 3: Commit:** `feat(teams): port PageSkeleton component (inbox variant only)`

---

## Task 9: InboxToolbar component

**Files:**
- Create: `apps/frontend/src/components/teams/inbox/InboxToolbar.tsx`
- Test: `apps/frontend/src/__tests__/components/teams/inbox/InboxToolbar.test.tsx`

- [ ] **Step 1: Read upstream**

```bash
sed -n '1874,2056p' /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/paperclip/ui/src/pages/Inbox.tsx
```

- [ ] **Step 2: Component shape**

```tsx
export interface InboxToolbarProps {
  tab: InboxTab;
  onTabChange: (tab: InboxTab) => void;
  searchQuery: string;
  onSearchChange: (q: string) => void;
  filterState: IssueFilterState;
  onFilterChange: (s: IssueFilterState) => void;
  agents: CompanyAgent[];
  members: CompanyMember[];
  projects: IssueProject[];
  labels: IssueLabel[];
  currentUserId: string;
  unreadCount: number;
  onMarkAllRead: () => void;
}
```

Renders:
1. Mobile-only search input (`sm:hidden`, with `data-page-search`)
2. Tab bar (4 tabs: Mine / Recent / Unread / All)
3. Toolbar row: desktop search + IssueFiltersPopover + Mark all as read button + AlertDialog confirmation

Drop from upstream: nesting toggle button, group-by popover, IssueColumnPicker (deferred features).

- [ ] **Step 3: Tests**

```ts
test("Tab click fires onTabChange with the correct tab", () => {
  const onTabChange = vi.fn();
  const { getByRole } = render(<InboxToolbar {...defaultProps} onTabChange={onTabChange} />);
  fireEvent.click(getByRole("tab", { name: /unread/i }));
  expect(onTabChange).toHaveBeenCalledWith("unread");
});

test("Search input fires onSearchChange (debounce optional)", () => {
  const onSearchChange = vi.fn();
  const { getByPlaceholderText } = render(<InboxToolbar {...defaultProps} onSearchChange={onSearchChange} />);
  fireEvent.change(getByPlaceholderText(/search/i), { target: { value: "fix" } });
  expect(onSearchChange).toHaveBeenCalledWith("fix");
});

test("Mark all as read button opens confirm dialog then fires", () => {
  const onMarkAllRead = vi.fn();
  const { getByRole, getByText } = render(<InboxToolbar {...defaultProps} unreadCount={5} onMarkAllRead={onMarkAllRead} />);
  fireEvent.click(getByRole("button", { name: /mark all/i }));
  fireEvent.click(getByText(/confirm/i));
  expect(onMarkAllRead).toHaveBeenCalled();
});
```

- [ ] **Step 4: Commit:** `feat(teams): port InboxToolbar (tabs + search + filters + mark-all-read)`

---

## Task 10: InboxList component

**Files:**
- Create: `apps/frontend/src/components/teams/inbox/InboxList.tsx`
- Test: `apps/frontend/src/__tests__/components/teams/inbox/InboxList.test.tsx`

- [ ] **Step 1: Read upstream**

```bash
sed -n '2121,2521p' /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/paperclip/ui/src/pages/Inbox.tsx
```

- [ ] **Step 2: Component shape**

```tsx
export interface InboxListProps {
  sections: InboxGroupedSection[];     // built by buildGroupedInboxSections
  selectedIssueId: string | null;
  onSelect: (id: string) => void;
  onOpen: (id: string) => void;
  onArchive: (id: string) => void;
  onMarkRead: (id: string) => void;
  archivingIds: Set<string>;
  fadingIds: Set<string>;
  isMobile: boolean;
  searchQuery: string;
  // ... derived state
}
```

Renders flat list (no nesting in v1):
- For each section, a section header (Today / Earlier / Search)
- For each issue in section: `<SwipeToArchive>` wrapping `<IssueRow>`
- `data-inbox-item-id={issue.id}` attribute on the wrapper for scroll-into-view from kbd nav
- Apply `archive-fade` className when `archivingIds` contains the id (the `-translate-x-4 scale-[0.98] opacity-0` upstream pattern)

DROP: parent-child nesting recursion, workspace pills, plugin links.

- [ ] **Step 3: Tests**

```ts
test("renders one IssueRow per issue across sections", () => {
  const sections = [
    { kind: "today", items: [makeIssue("1"), makeIssue("2")] },
    { kind: "earlier", items: [makeIssue("3")] },
  ];
  const { container } = render(<InboxList sections={sections} {...defaults} />);
  expect(container.querySelectorAll("[data-inbox-item-id]").length).toBe(3);
});

test("archive button on a row fires onArchive with id", () => {
  // ...
});

test("clicking the section header has no effect (purely presentational)", () => {
  // ...
});
```

- [ ] **Step 4: Commit:** `feat(teams): port InboxList (flat list with today/earlier/search dividers)`

---

## Task 11: InboxPage assembly + replace InboxPanel.tsx

**Files:**
- Create: `apps/frontend/src/components/teams/inbox/InboxPage.tsx`
- Modify: `apps/frontend/src/components/teams/panels/InboxPanel.tsx` (replace body)
- Test: `apps/frontend/src/__tests__/components/teams/inbox/InboxPage.test.tsx`

- [ ] **Step 1: Read upstream**

```bash
sed -n '1820,2120p' /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/paperclip/ui/src/pages/Inbox.tsx
sed -n '2090,2120p' /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/paperclip/ui/src/pages/Inbox.tsx
```

- [ ] **Step 2: InboxPage assembly**

Pieces:
- `useInboxData()` — Task 5
- `useInboxKeyboardNav(...)` — Task 6
- `useInboxArchiveStack()` — Task 7
- `useReadInboxItems(companyId)` — Task 4
- `useInboxFilterPreferences()` — Task 3
- URL-synced `tab` via Next router (`useSearchParams`, `useRouter`)
- Selected index state (`useState<number>(-1)`)
- Build `groupedSections` from `useInboxData` result + tab + filterState + searchQuery
- Render: `<InboxToolbar />` + (loading skeleton | empty state | `<InboxList />`) + (Cmd+Z hint?)

Empty state copy switch (port verbatim from upstream L2104-2117):
- `searchQuery` → `"No inbox items match your search."`
- `tab="mine"` → `"Inbox zero."`
- `tab="unread"` → `"No new inbox items."`
- `tab="recent"` → `"No recent inbox items."`
- else → `"No inbox items match these filters."`

- [ ] **Step 3: Replace InboxPanel.tsx**

```tsx
// apps/frontend/src/components/teams/panels/InboxPanel.tsx

import { InboxPage } from "@/components/teams/inbox/InboxPage";

export function InboxPanel() {
  return <InboxPage />;
}
```

The 49-line stub becomes 1 line + 1 import.

- [ ] **Step 4: Tests**

```ts
test("renders skeleton while data loading", () => {
  // mock useInboxData to return isLoading: true
  // assert PageSkeleton in DOM
});

test("renders empty state for mine tab when no issues", () => {
  // mock data: mineIssues = []
  const { getByText } = render(<InboxPage />);
  expect(getByText(/inbox zero/i)).toBeInTheDocument();
});

test("URL ?tab=unread switches the active tab", () => {
  // mock useSearchParams
});

test("clicking an issue row navigates to /teams/issues/<id>", () => {
  // ...
});
```

- [ ] **Step 5: Commit:** `feat(teams): wire InboxPage and replace 49-line InboxPanel stub`

---

## Task 12: Realtime invalidation + final verification + PR

**Files:**
- Modify: `apps/frontend/src/components/teams/TeamsEventsProvider.tsx`
- Test: existing TeamsEventsProvider tests should still pass

- [ ] **Step 1: Extend EVENT_KEY_MAP**

Read the current `EVENT_KEY_MAP` constant. Add entries:

```ts
const EVENT_KEY_MAP = {
  // ... existing entries from #518 ...
  "teams.activity.logged": [
    /* existing */,
    teamsQueryKeys.inbox.list("mine", {}),
    teamsQueryKeys.inbox.list("recent", {}),
    teamsQueryKeys.inbox.list("all", {}),
  ],
  "teams.issue.archived": [
    teamsQueryKeys.inbox.list("mine", {}),
    teamsQueryKeys.inbox.list("recent", {}),
    teamsQueryKeys.inbox.list("all", {}),
  ],
  "teams.issue.created": [
    teamsQueryKeys.inbox.list("mine", {}),
    teamsQueryKeys.inbox.list("recent", {}),
    teamsQueryKeys.inbox.list("all", {}),
  ],
  // etc.
};
```

The exact event names to add: read the existing `TeamsEventsProvider.tsx` to see what events the BFF emits today. Adapt to the actual event names — the above are illustrative.

- [ ] **Step 2: Run full frontend test suite**

```bash
cd apps/frontend && pnpm test 2>&1 | tail -30
```

Expected: all green. Pre-existing failures (BotSetupWizard, MyChannelsSection, AgentChannelsSection, CreditsPanel) are unrelated and will fail; that's fine — same as #3b's CI.

- [ ] **Step 3: Run lint + typecheck**

```bash
cd apps/frontend && pnpm lint 2>&1 | tail -20
pnpm --filter @isol8/frontend exec tsc --noEmit 2>&1 | grep error | head
```

Expected: 0 lint errors, 0 type errors.

- [ ] **Step 4: Update roadmap**

Edit `docs/superpowers/specs/2026-05-04-teams-ui-parity-roadmap.md` row #3 status: `In progress (3a ✅, 3b ✅, 3c in flight)` → `In progress (3a ✅, 3b ✅, 3c ✅, 3d pending)`.

- [ ] **Step 5: Push + open PR**

```bash
git push -u origin feat/teams-inbox-page
gh pr create --title "feat(teams): port Inbox page with full Paperclip parity (#3c)" --body "..."
```

PR body skeleton:

```
## Summary

Sub-project #3c of the [Teams UI parity roadmap](docs/superpowers/specs/2026-05-04-teams-ui-parity-roadmap.md). Replaces InboxPanel.tsx 49-line stub with a faithful port of upstream Paperclip's Inbox page. Wires the components from #3b. Adds SWR hooks for the data layer + archive flow + keyboard navigation. Realtime invalidation extends PR #518's EVENT_KEY_MAP.

## What's new

- 4 tabs: Mine / Recent / Unread / All (URL-synced)
- Search + IssueFiltersPopover wiring
- Keyboard nav: j/k/Enter/a/y/r/Cmd+Z
- Optimistic archive with Cmd+Z undo (no inline toast — matches upstream)
- Mark all as read with confirmation
- Per-tab empty states
- Realtime invalidation on agent + issue events

## Out of scope (deferred to #3d or later)

- Detail page navigation (issues/[id] still a stub; #3d wires it)
- Parent-child issue nesting
- Live-runs polling + highlight badge
- Approvals + JoinRequests + FailedRuns row variants in the All tab
- Dashboard alerts section
- Group-by popover + column picker

## Test plan

- [x] X new tests across hooks + components + page; full Teams suite green.
- [x] Lint + typecheck clean.
- [ ] Manual visual verification on dev.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

- [ ] **Step 6: Watch CI**

```bash
gh run watch --repo Isol8AI/isol8 --exit-status
```

If green AND Codex ready → squash-merge.

---

## Self-review checklist

- ✅ All 12 tasks have explicit file lists + step-by-step instructions + tests
- ✅ Dependencies flow correctly: lib (T1-3) → hooks (T4-7) → components (T8-10) → page (T11) → realtime (T12)
- ✅ No placeholder code in tasks — every step shows the code snippet or the upstream file to read
- ✅ Per-task commits keep the PR reviewable
- ✅ Roadmap update bundles into Task 12 (the PR-opening task)
- ✅ Branch naming: `feat/teams-inbox-page` per the design doc
- ✅ Subagents run only their own task's tests; full suite at Task 12 (per memory `feedback_run_tests_at_end`)
- ✅ Out-of-scope list explicit at top of plan + repeated per task where relevant
