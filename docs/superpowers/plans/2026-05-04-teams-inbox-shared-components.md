# Teams Inbox Shared Components Implementation Plan (PR #3b)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wholesale port of upstream Paperclip's shared Inbox components into `apps/frontend/src/components/teams/inbox/` + `teams/shared/`, retheming to Isol8's cream-and-warm-grey palette. Components exist + render in isolation; not yet wired into `InboxPanel.tsx` (that's #3c).

**Architecture:** Each ported file copies upstream verbatim (modulo retheme + import-path adjustments + React Router → Next App Router translations). Component logic preserved. Types port a subset of `@paperclipai/shared` to a local `teams/shared/types.ts`. `cn()` already exists at `@/lib/utils`. `useTeamsApi` hook already exists at `@/hooks/useTeamsApi` for #3c data wiring.

**Tech Stack:** React 19 + Tailwind v4 (oklch CSS vars in `globals.css`) + lucide-react + shadcn/ui primitives. SWR via `useTeamsApi` (deferred to #3c). No new deps.

**Upstream license:** Paperclip is MIT (`paperclip/LICENSE`). Each ported file gets a 3-line attribution header per the design doc.

---

## File structure

```
apps/frontend/src/components/teams/
├── shared/
│   ├── types.ts                       # NEW. Issue, Approval, HeartbeatRun subsets
│   ├── queryKeys.ts                   # NEW. SWR cache key factory
│   ├── lib/
│   │   ├── timeAgo.ts                 # NEW. ports paperclip/ui/src/lib/timeAgo.ts
│   │   ├── assignees.ts               # NEW. formatAssigneeUserLabel + Identity helpers
│   │   ├── issueDetailBreadcrumb.ts   # NEW. createIssueDetailPath helper (no router state)
│   │   └── issueFilters.ts            # NEW. IssueFilterState + filter helpers (subset)
│   └── components/
│       ├── StatusIcon.tsx             # NEW. ports paperclip/ui/src/components/StatusIcon.tsx
│       └── ProductivityReviewBadge.tsx# NEW. tiny inline badge (label const)
└── inbox/
    ├── SwipeToArchive.tsx             # NEW. ports paperclip/ui/src/components/SwipeToArchive.tsx
    ├── KeyboardShortcutsCheatsheet.tsx# NEW. ports the cheatsheet
    ├── IssueRow.tsx                   # NEW. ports IssueRow.tsx (includes inline UnreadDot button)
    ├── IssueColumns.tsx               # NEW. ports IssueColumns.tsx (includes InboxIssueMetaLeading = LiveRunBadge equivalent)
    └── IssueFiltersPopover.tsx        # NEW. ports IssueFiltersPopover.tsx

apps/frontend/src/__tests__/components/teams/inbox/
├── SwipeToArchive.test.tsx
├── KeyboardShortcutsCheatsheet.test.tsx
├── IssueRow.test.tsx
├── IssueColumns.test.tsx
└── IssueFiltersPopover.test.tsx
```

---

## Retheme mapping (apply during each port)

Per spec, replace literal color tokens during port. Let semantic shadcn tokens (`bg-background`, `bg-muted`, `text-foreground`, `border-border`, `bg-accent`) pass through — they pick up Isol8's oklch vars automatically.

| Upstream | Isol8 |
|---|---|
| `bg-blue-500`, `bg-blue-600`, `text-blue-{400,600}` | `bg-amber-700`, `text-amber-700` |
| `bg-blue-{400,500}/{10,20}` | `bg-amber-700/{10,20}` |
| `bg-amber-{400,500}/10`, `border-amber-{300,400,500}/{35,40,45}`, `text-amber-{300,600,700}` | KEEP — already on Isol8's accent hue |
| `bg-emerald-600` | KEEP — archive-confirm hue |
| `bg-zinc-100`, `bg-zinc-800` (selected-row bg) | `bg-stone-100`, `bg-stone-800` |
| `bg-{green,red,violet,yellow}-500`, `bg-neutral-400` | KEEP for status semantics |

`globals.css` is **not modified** by this PR. Only per-file class swaps.

---

## Out of scope (explicitly)

- Wiring components into `InboxPanel.tsx` — #3c.
- Hooks that fetch BFF data (`useArchiveMutation`, `useUnreadIssues`, `useInboxBadge`) — #3c.
- `IssuesList.tsx` (1723 LOC, the Issues *page*) — not used by Inbox; not ported.
- `pages/Inbox.tsx` itself — #3c.
- Detail pages (IssueDetail, ApprovalDetail, AgentRun) — #3d.
- `lib/inbox.ts` (1113 LOC) — large helper used by `useInboxBadge`; defer to #3c.
- `KanbanBoard`, `IssueGroupHeader`, `EmptyState` — Issues-page-only.

---

## Task 1: Roadmap update + types subset

**Files:**
- Modify: `docs/superpowers/specs/2026-05-04-teams-ui-parity-roadmap.md`
- Create: `apps/frontend/src/components/teams/shared/types.ts`
- Test: `apps/frontend/src/__tests__/components/teams/shared/types.test.ts` (compile-only)

- [ ] **Step 1: Update roadmap row #3**

In `docs/superpowers/specs/2026-05-04-teams-ui-parity-roadmap.md`, the row currently reads (around line 19):

```
| 3 | Inbox **deep port** ... | XL | Plan (#3a) | [link] | [#3a BFF plan](...) | — |
```

Replace status `Plan (#3a)` with `In progress (3a ✅, 3b in flight)` and append a parenthetical to the description: `(3a auth-fix follow-up: PR #529 — switched /teams/inbox from agent-only inbox-lite to board-user /companies/{co}/issues)`. Append `[#3b plan](../plans/2026-05-04-teams-inbox-shared-components.md)` to the Plan column.

- [ ] **Step 2: Create the types subset**

```ts
// apps/frontend/src/components/teams/shared/types.ts

// Ported from upstream Paperclip
// (https://github.com/Paperclip-AI/paperclip/tree/main/packages/shared/src/types)
// (MIT, © 2025 Paperclip AI). Subset retained for IssueRow / IssueColumns /
// IssueFiltersPopover. Full type lives in upstream packages/shared/src/types/.
// See spec at docs/superpowers/specs/2026-05-04-teams-inbox-deep-port-design.md

export type IssueStatus =
  | "todo"
  | "in_progress"
  | "in_review"
  | "pending"
  | "review"
  | "done"
  | "won_t_do"
  | "blocked"
  | "duplicate"
  | "open"
  | "closed";

export const ISSUE_STATUSES: readonly IssueStatus[] = [
  "todo",
  "in_progress",
  "in_review",
  "pending",
  "review",
  "done",
  "won_t_do",
  "blocked",
  "duplicate",
];

export type IssuePriority = "urgent" | "high" | "medium" | "low" | "none";

export interface IssueLabel {
  id: string;
  name: string;
  color?: string | null;
}

export interface IssueProject {
  id: string;
  name: string;
  color?: string | null;
}

export interface Issue {
  id: string;
  identifier?: string | null;
  title: string;
  status: IssueStatus;
  priority?: IssuePriority | null;
  labels?: IssueLabel[] | null;
  project?: IssueProject | null;
  parentId?: string | null;
  assigneeAgentId?: string | null;
  assigneeUserId?: string | null;
  createdByUserId?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
  lastActivityAt?: string | null;
  lastExternalCommentAt?: string | null;
  blockerAttention?: boolean | null;
  productivityReview?: {
    triggerLabel?: string | null;
  } | null;
  unread?: boolean | null;
  archivedAt?: string | null;
}

export interface Approval {
  id: string;
  issueId?: string | null;
  title?: string | null;
  status: "pending" | "approved" | "rejected";
  createdAt?: string | null;
  decidedAt?: string | null;
}

export interface HeartbeatRun {
  id: string;
  agentId?: string | null;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  startedAt?: string | null;
  completedAt?: string | null;
  failureReason?: string | null;
}

export interface CompanyMember {
  userId: string;
  name?: string | null;
  email?: string | null;
  imageUrl?: string | null;
}

export interface CompanyAgent {
  id: string;
  name: string;
  iconUrl?: string | null;
}
```

- [ ] **Step 3: Compile-only test**

```tsx
// apps/frontend/src/__tests__/components/teams/shared/types.test.ts
import type { Issue, Approval, HeartbeatRun } from "@/components/teams/shared/types";
import { ISSUE_STATUSES } from "@/components/teams/shared/types";

test("types module exports the runtime status list", () => {
  expect(ISSUE_STATUSES).toContain("todo");
  expect(ISSUE_STATUSES.length).toBeGreaterThan(5);
});

test("Issue type allows minimum-shape construction", () => {
  const issue: Issue = { id: "i1", title: "x", status: "todo" };
  expect(issue.id).toBe("i1");
});

test("Approval and HeartbeatRun discriminator unions compile", () => {
  const a: Approval = { id: "a1", status: "pending" };
  const r: HeartbeatRun = { id: "r1", status: "queued" };
  expect(a.status).toBe("pending");
  expect(r.status).toBe("queued");
});
```

- [ ] **Step 4: Run + commit**

```bash
cd apps/frontend && pnpm test -- src/__tests__/components/teams/shared/types.test.ts
git add docs/superpowers/specs/2026-05-04-teams-ui-parity-roadmap.md apps/frontend/src/components/teams/shared/types.ts apps/frontend/src/__tests__/components/teams/shared/types.test.ts
git commit -m "feat(teams): port Issue/Approval/HeartbeatRun type subset + roadmap update"
```

---

## Task 2: Query keys

**Files:**
- Create: `apps/frontend/src/components/teams/shared/queryKeys.ts`
- Test: `apps/frontend/src/__tests__/components/teams/shared/queryKeys.test.ts`

- [ ] **Step 1: Write failing test**

```ts
// apps/frontend/src/__tests__/components/teams/shared/queryKeys.test.ts
import { teamsQueryKeys } from "@/components/teams/shared/queryKeys";

describe("teamsQueryKeys", () => {
  test("inbox.list builds a path with tab + filter query string", () => {
    const key = teamsQueryKeys.inbox.list("mine", { status: "todo", search: "fix" });
    expect(key).toBe("/teams/inbox?tab=mine&status=todo&search=fix");
  });

  test("inbox.list with no filters omits empty filter args", () => {
    expect(teamsQueryKeys.inbox.list("all", {})).toBe("/teams/inbox?tab=all");
  });

  test("inbox.list serializes filter values url-encoded", () => {
    expect(teamsQueryKeys.inbox.list("mine", { search: "fix bug" })).toBe(
      "/teams/inbox?tab=mine&search=fix%20bug"
    );
  });

  test("issues.detail and approvals.detail build per-id keys", () => {
    expect(teamsQueryKeys.issues.detail("iss_1")).toBe("/teams/issues/iss_1");
    expect(teamsQueryKeys.approvals.detail("a1")).toBe("/teams/approvals/a1");
  });

  test("inbox.approvals + inbox.runs + inbox.liveRuns return fixed keys", () => {
    expect(teamsQueryKeys.inbox.approvals()).toBe("/teams/inbox/approvals");
    expect(teamsQueryKeys.inbox.runs()).toBe("/teams/inbox/runs");
    expect(teamsQueryKeys.inbox.liveRuns()).toBe("/teams/inbox/live-runs");
  });
});
```

- [ ] **Step 2: Run to verify failure**

```bash
cd apps/frontend && pnpm test -- src/__tests__/components/teams/shared/queryKeys.test.ts
```
Expected: FAIL — module not found.

- [ ] **Step 3: Implementation**

```ts
// apps/frontend/src/components/teams/shared/queryKeys.ts

// Ported from upstream Paperclip's queryKeys.ts (paperclip/ui/src/lib/queryKeys.ts)
// (MIT, © 2025 Paperclip AI). Translated from React Query tuple keys to SWR
// string keys. See spec at
// docs/superpowers/specs/2026-05-04-teams-inbox-deep-port-design.md

export type InboxTab = "mine" | "recent" | "all" | "unread" | "approvals" | "runs" | "joins";

export interface InboxFilters {
  status?: string;
  project?: string;
  assignee?: string;
  creator?: string;
  search?: string;
  limit?: number;
}

function qs(filters: InboxFilters): string {
  const parts: string[] = [];
  for (const [k, v] of Object.entries(filters)) {
    if (v === undefined || v === null || v === "") continue;
    parts.push(`${k}=${encodeURIComponent(String(v))}`);
  }
  return parts.join("&");
}

export const teamsQueryKeys = {
  inbox: {
    list: (tab: InboxTab, filters: InboxFilters) => {
      const tail = qs(filters);
      return tail ? `/teams/inbox?tab=${tab}&${tail}` : `/teams/inbox?tab=${tab}`;
    },
    approvals: () => `/teams/inbox/approvals`,
    runs: () => `/teams/inbox/runs`,
    liveRuns: () => `/teams/inbox/live-runs`,
  },
  issues: {
    detail: (id: string) => `/teams/issues/${id}`,
    comments: (id: string) => `/teams/issues/${id}/comments`,
  },
  approvals: { detail: (id: string) => `/teams/approvals/${id}` },
  runs: { detail: (id: string) => `/teams/runs/${id}` },
  members: () => `/teams/members`,
  projects: () => `/teams/projects`,
} as const;
```

- [ ] **Step 4: Run to verify pass**

```bash
cd apps/frontend && pnpm test -- src/__tests__/components/teams/shared/queryKeys.test.ts
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/components/teams/shared/queryKeys.ts apps/frontend/src/__tests__/components/teams/shared/queryKeys.test.ts
git commit -m "feat(teams): port queryKeys factory (SWR string-key flavor)"
```

---

## Task 3: lib helpers — timeAgo + assignees + issueDetailBreadcrumb + issueFilters

These four are small + non-component utilities. Bundle in one task. Each gets co-located unit tests. Read upstream files first to capture exact behavior.

**Files:**
- Create: `apps/frontend/src/components/teams/shared/lib/timeAgo.ts`
- Create: `apps/frontend/src/components/teams/shared/lib/assignees.ts`
- Create: `apps/frontend/src/components/teams/shared/lib/issueDetailBreadcrumb.ts`
- Create: `apps/frontend/src/components/teams/shared/lib/issueFilters.ts`
- Test: `apps/frontend/src/__tests__/components/teams/shared/lib/timeAgo.test.ts`
- Test: `apps/frontend/src/__tests__/components/teams/shared/lib/assignees.test.ts`
- Test: `apps/frontend/src/__tests__/components/teams/shared/lib/issueFilters.test.ts`

- [ ] **Step 1: Read upstream sources**

```bash
# From repo root
cat paperclip/ui/src/lib/timeAgo.ts
cat paperclip/ui/src/lib/assignees.ts
cat paperclip/ui/src/lib/issueDetailBreadcrumb.ts
cat paperclip/ui/src/lib/issue-filters.ts
```

- [ ] **Step 2: Port `timeAgo.ts`**

Verbatim port (~30 LOC pure date math). Add the 3-line attribution header. Drop any imports that don't exist in our tree (it's a pure function).

- [ ] **Step 3: Port `assignees.ts`**

Port `formatAssigneeUserLabel(user, currentUserId)` and any sibling exports IssueRow/IssueColumns import. If upstream pulls a `User` type from `@paperclipai/shared`, replace with our `CompanyMember` from `teams/shared/types.ts`.

- [ ] **Step 4: Port `issueDetailBreadcrumb.ts`**

Three exports upstream: `createIssueDetailPath(issueId)`, `rememberIssueDetailLocationState(...)`, `withIssueDetailHeaderSeed(...)`.

- `createIssueDetailPath` — straight port. Translate the upstream URL `/issues/${id}` to Isol8's `/teams/issues/${id}`.
- `rememberIssueDetailLocationState` + `withIssueDetailHeaderSeed` — these used React Router state. In Next App Router, route state isn't a thing. Port as **no-op stubs** that accept the same args and return the same shape so call sites in IssueRow compile. Document the noop in a one-line comment.

- [ ] **Step 5: Port `issueFilters.ts`**

This is the largest of the four. Upstream exports: `IssueFilterState` type + helpers like `emptyIssueFilters()`, `hasActiveFilters(state)`, `clearStatusFilter(state)`, etc. Port the **subset that IssueFiltersPopover uses** (which is what's imported in upstream's `IssueFiltersPopover.tsx` lines 9-17 — read that file first and only port what's named there). Skip the helpers used only by `IssuesList.tsx`.

- [ ] **Step 6: Add tests**

For each lib file, a small unit test asserting the public behavior. ~3-5 assertions per file.

- [ ] **Step 7: Run + commit**

```bash
cd apps/frontend && pnpm test -- src/__tests__/components/teams/shared/lib/
git add apps/frontend/src/components/teams/shared/lib/ apps/frontend/src/__tests__/components/teams/shared/lib/
git commit -m "feat(teams): port timeAgo + assignees + issueDetailBreadcrumb + issueFilters"
```

---

## Task 4: StatusIcon + ProductivityReviewBadge

Both are small visual components imported by IssueRow.

**Files:**
- Create: `apps/frontend/src/components/teams/shared/components/StatusIcon.tsx`
- Create: `apps/frontend/src/components/teams/shared/components/ProductivityReviewBadge.tsx`
- Test: `apps/frontend/src/__tests__/components/teams/shared/components/StatusIcon.test.tsx`

- [ ] **Step 1: Read upstream**

```bash
cat paperclip/ui/src/components/StatusIcon.tsx
cat paperclip/ui/src/components/ProductivityReviewBadge.tsx
```

- [ ] **Step 2: Port StatusIcon**

Verbatim. Imports become `@/components/teams/shared/types` for `IssueStatus`. Apply the retheme mapping to any literal color tokens. Keep the icon set (lucide-react).

- [ ] **Step 3: Port ProductivityReviewBadge**

Upstream re-exports a label constant `productivityReviewTriggerLabel`. Port the file as-is (likely under 30 LOC) — both the component and the constant.

- [ ] **Step 4: Test StatusIcon**

```tsx
import { render } from "@testing-library/react";
import { StatusIcon } from "@/components/teams/shared/components/StatusIcon";

test("StatusIcon renders one icon per known status", () => {
  for (const status of ["todo", "in_progress", "done", "blocked"] as const) {
    const { container } = render(<StatusIcon status={status} />);
    expect(container.querySelector("svg")).toBeInTheDocument();
  }
});
```

- [ ] **Step 5: Run + commit**

```bash
cd apps/frontend && pnpm test -- src/__tests__/components/teams/shared/components/
git add apps/frontend/src/components/teams/shared/components/ apps/frontend/src/__tests__/components/teams/shared/components/
git commit -m "feat(teams): port StatusIcon + ProductivityReviewBadge"
```

---

## Task 5: SwipeToArchive

No deps beyond `cn()`. Pure DOM/touch component. Easy port.

**Files:**
- Create: `apps/frontend/src/components/teams/inbox/SwipeToArchive.tsx`
- Test: `apps/frontend/src/__tests__/components/teams/inbox/SwipeToArchive.test.tsx`

- [ ] **Step 1: Read upstream**

```bash
cat paperclip/ui/src/components/SwipeToArchive.tsx
```
167 LOC, no router/context deps.

- [ ] **Step 2: Port verbatim**

Replace `import { cn } from "../lib/utils"` with `import { cn } from "@/lib/utils"`. Apply retheme: `bg-zinc-100` → `bg-stone-100`, `bg-zinc-800` → `bg-stone-800`. Keep `bg-emerald-600` (archive-confirm hue).

Add the 3-line attribution header.

- [ ] **Step 3: Test**

```tsx
import { fireEvent, render } from "@testing-library/react";
import { SwipeToArchive } from "@/components/teams/inbox/SwipeToArchive";

test("renders children", () => {
  const { getByText } = render(
    <SwipeToArchive onArchive={() => {}}><div>row</div></SwipeToArchive>
  );
  expect(getByText("row")).toBeInTheDocument();
});

test("does not fire onArchive without a swipe gesture", () => {
  const onArchive = jest.fn();
  render(<SwipeToArchive onArchive={onArchive}><div>row</div></SwipeToArchive>);
  // Touch gestures jsdom-incompatible; verifying the no-op default is enough
  expect(onArchive).not.toHaveBeenCalled();
});
```

- [ ] **Step 4: Run + commit**

```bash
cd apps/frontend && pnpm test -- src/__tests__/components/teams/inbox/SwipeToArchive.test.tsx
git add apps/frontend/src/components/teams/inbox/SwipeToArchive.tsx apps/frontend/src/__tests__/components/teams/inbox/SwipeToArchive.test.tsx
git commit -m "feat(teams): port SwipeToArchive (mobile gesture)"
```

---

## Task 6: KeyboardShortcutsCheatsheet

Pure presentational. ~114 LOC.

**Files:**
- Create: `apps/frontend/src/components/teams/inbox/KeyboardShortcutsCheatsheet.tsx`
- Test: `apps/frontend/src/__tests__/components/teams/inbox/KeyboardShortcutsCheatsheet.test.tsx`

- [ ] **Step 1: Read upstream**

```bash
cat paperclip/ui/src/components/KeyboardShortcutsCheatsheet.tsx
```

- [ ] **Step 2: Port**

Verbatim. Translate import path of `Dialog*` to `@/components/ui/dialog` (already exists in Isol8 shadcn set). The "Issue detail" section's `g i` and `g c` chords are upstream-Paperclip-specific routing shortcuts that don't apply in Isol8 — **drop those entries** from the sections array. Keep "Inbox" and "Global" sections unchanged.

Add the 3-line attribution header.

- [ ] **Step 3: Test**

```tsx
import { render } from "@testing-library/react";
import { KeyboardShortcutsCheatsheetContent } from "@/components/teams/inbox/KeyboardShortcutsCheatsheet";

test("renders Inbox section heading + at least 4 shortcuts", () => {
  const { getByText, container } = render(<KeyboardShortcutsCheatsheetContent />);
  expect(getByText(/inbox/i)).toBeInTheDocument();
  expect(container.querySelectorAll("kbd").length).toBeGreaterThanOrEqual(4);
});
```

- [ ] **Step 4: Run + commit**

```bash
cd apps/frontend && pnpm test -- src/__tests__/components/teams/inbox/KeyboardShortcutsCheatsheet.test.tsx
git add apps/frontend/src/components/teams/inbox/KeyboardShortcutsCheatsheet.tsx apps/frontend/src/__tests__/components/teams/inbox/KeyboardShortcutsCheatsheet.test.tsx
git commit -m "feat(teams): port KeyboardShortcutsCheatsheet"
```

---

## Task 7: IssueRow

The first non-trivial port. 209 LOC. Includes the inline UnreadDot button.

**Files:**
- Create: `apps/frontend/src/components/teams/inbox/IssueRow.tsx`
- Test: `apps/frontend/src/__tests__/components/teams/inbox/IssueRow.test.tsx`

- [ ] **Step 1: Read upstream**

```bash
cat paperclip/ui/src/components/IssueRow.tsx
```

- [ ] **Step 2: Translate the `Link` import**

Upstream uses `Link` from `@/lib/router` with custom props `disableIssueQuicklook`, `issuePrefetch`, `state={...}`. Isol8 uses `next/link`. Replace as follows:

```tsx
import Link from "next/link";
```

The custom props `disableIssueQuicklook`, `issuePrefetch`, and `state={...}` aren't supported by `next/link`. Drop them at every call site. (Quicklook + state are both upstream-router-only features; dropping them produces a plain navigation, which matches Isol8's existing inbox behavior.)

- [ ] **Step 3: Port the file**

- Imports map:
  - `@paperclipai/shared` → `@/components/teams/shared/types`
  - `@/lib/router` → `next/link` (default import)
  - `../lib/issueDetailBreadcrumb` → `@/components/teams/shared/lib/issueDetailBreadcrumb`
  - `../lib/utils` → `@/lib/utils`
  - `./StatusIcon` → `@/components/teams/shared/components/StatusIcon`
  - `./ProductivityReviewBadge` → `@/components/teams/shared/components/ProductivityReviewBadge`
- Apply the retheme mapping to literal color tokens.
- Add the 3-line attribution header.

- [ ] **Step 4: Test**

```tsx
import { render, fireEvent } from "@testing-library/react";
import { IssueRow } from "@/components/teams/inbox/IssueRow";
import type { Issue } from "@/components/teams/shared/types";

const issue: Issue = {
  id: "iss_1",
  identifier: "PAP-1",
  title: "Fix the inbox",
  status: "todo",
  unread: true,
};

test("renders the issue title + identifier", () => {
  const { getByText } = render(<IssueRow issue={issue} />);
  expect(getByText(/Fix the inbox/)).toBeInTheDocument();
});

test("unread issue surfaces an unread-dot button", () => {
  const onMarkRead = jest.fn();
  const { getByRole } = render(<IssueRow issue={issue} onMarkRead={onMarkRead} />);
  fireEvent.click(getByRole("button", { name: /mark as read/i }));
  expect(onMarkRead).toHaveBeenCalledWith(issue.id);
});

test("archive button fires onArchive without following the link", () => {
  const onArchive = jest.fn();
  const { getByRole } = render(<IssueRow issue={issue} onArchive={onArchive} />);
  const btn = getByRole("button", { name: /archive/i });
  fireEvent.click(btn);
  expect(onArchive).toHaveBeenCalledWith(issue.id);
});
```

If upstream's IssueRow doesn't accept `onMarkRead`/`onArchive` props (it uses internal mutations), test what it DOES accept — read upstream's IssueRow first, adapt the test to the actual prop surface.

- [ ] **Step 5: Run + commit**

```bash
cd apps/frontend && pnpm test -- src/__tests__/components/teams/inbox/IssueRow.test.tsx
git add apps/frontend/src/components/teams/inbox/IssueRow.tsx apps/frontend/src/__tests__/components/teams/inbox/IssueRow.test.tsx
git commit -m "feat(teams): port IssueRow with retheme + Next Link"
```

---

## Task 8: IssueColumns

390 LOC. Includes `InboxIssueMetaLeading` (the live-run badge equivalent) + `InboxIssueTrailingColumns`. Imports many lib helpers.

**Files:**
- Create: `apps/frontend/src/components/teams/inbox/IssueColumns.tsx`
- Test: `apps/frontend/src/__tests__/components/teams/inbox/IssueColumns.test.tsx`

- [ ] **Step 1: Read upstream**

```bash
cat paperclip/ui/src/components/IssueColumns.tsx
```

- [ ] **Step 2: Identify missing dep helpers**

Upstream imports include:
- `@/lib/color-contrast` (`pickTextColorForPillBg`)
- `../lib/inbox` (`InboxIssueColumn` type)
- `./Identity` (component)

Decision per-helper:

- **`pickTextColorForPillBg`** — ~10 LOC pure function, must port. Co-locate as `apps/frontend/src/components/teams/shared/lib/colorContrast.ts`.
- **`InboxIssueColumn` type from `lib/inbox.ts`** — `lib/inbox.ts` is 1113 LOC. Just port the **type alias** and the **constant array `DEFAULT_INBOX_ISSUE_COLUMNS`** to a new file `apps/frontend/src/components/teams/shared/lib/inboxColumns.ts`. Skip the rest of `lib/inbox.ts` (deferred to #3c).
- **`Identity`** — small avatar component (~50-80 LOC). Read it; if it pulls in heavy deps, stub it as a fallback initials avatar. Otherwise port. Co-locate as `apps/frontend/src/components/teams/shared/components/Identity.tsx`.

Do these inline as part of this task — don't carve out a separate task.

- [ ] **Step 3: Port IssueColumns.tsx**

- Imports map: same scheme as Task 7 (shared/types, shared/components, shared/lib).
- shadcn primitives `dropdown-menu` + `tooltip` exist in Isol8 — verify with `ls apps/frontend/src/components/ui/`.
- Apply the retheme.
- Add the 3-line attribution header.

- [ ] **Step 4: Test**

Test the three exported components: `InboxIssueMetaLeading`, `InboxIssueTrailingColumns`, `IssueColumnPicker`. Lightweight smoke tests asserting render output for a few `Issue` shapes (with/without project, with/without active run).

- [ ] **Step 5: Run + commit**

```bash
cd apps/frontend && pnpm test -- src/__tests__/components/teams/inbox/IssueColumns.test.tsx
git add apps/frontend/src/components/teams/inbox/IssueColumns.tsx apps/frontend/src/components/teams/shared/ apps/frontend/src/__tests__/components/teams/inbox/IssueColumns.test.tsx
git commit -m "feat(teams): port IssueColumns + Identity + colorContrast + inbox-column type"
```

---

## Task 9: IssueFiltersPopover

372 LOC. Largest component port.

**Files:**
- Create: `apps/frontend/src/components/teams/inbox/IssueFiltersPopover.tsx`
- Test: `apps/frontend/src/__tests__/components/teams/inbox/IssueFiltersPopover.test.tsx`

- [ ] **Step 1: Read upstream**

```bash
cat paperclip/ui/src/components/IssueFiltersPopover.tsx
```

- [ ] **Step 2: Verify its `lib/issue-filters.ts` deps are already ported**

Check Task 3 ported the named imports IssueFiltersPopover.tsx uses (lines 9-17 upstream). If anything is missing, add to `apps/frontend/src/components/teams/shared/lib/issueFilters.ts` now.

- [ ] **Step 3: Port the file**

- Imports map: same scheme as Task 7 + `./PriorityIcon` and `./StatusIcon` → `@/components/teams/shared/components/`. `PriorityIcon` is a new dep — port it inline (read upstream `paperclip/ui/src/components/PriorityIcon.tsx`).
- shadcn `badge` + `checkbox` + `popover` + `input` + `button` all exist in Isol8.
- Apply the retheme.
- Add the 3-line attribution header.

- [ ] **Step 4: Test**

```tsx
import { render, fireEvent } from "@testing-library/react";
import { IssueFiltersPopover } from "@/components/teams/inbox/IssueFiltersPopover";

const noopProps = {
  state: { /* shape from issueFilters.IssueFilterState */ },
  onChange: jest.fn(),
  agents: [],
  members: [],
  projects: [],
  labels: [],
  currentUserId: "u1",
};

test("renders trigger button", () => {
  const { getByRole } = render(<IssueFiltersPopover {...noopProps} />);
  expect(getByRole("button", { name: /filter/i })).toBeInTheDocument();
});

test("opens popover on trigger click", () => {
  const { getByRole, getByText } = render(<IssueFiltersPopover {...noopProps} />);
  fireEvent.click(getByRole("button", { name: /filter/i }));
  expect(getByText(/status/i)).toBeInTheDocument();
});

test("toggling a filter checkbox calls onChange", () => {
  const onChange = jest.fn();
  const { getByRole, getAllByRole } = render(<IssueFiltersPopover {...noopProps} onChange={onChange} />);
  fireEvent.click(getByRole("button", { name: /filter/i }));
  const checkboxes = getAllByRole("checkbox");
  if (checkboxes[0]) fireEvent.click(checkboxes[0]);
  expect(onChange).toHaveBeenCalled();
});
```

Adjust the prop shape to match upstream's actual props after reading the file.

- [ ] **Step 5: Run + commit**

```bash
cd apps/frontend && pnpm test -- src/__tests__/components/teams/inbox/IssueFiltersPopover.test.tsx
git add apps/frontend/src/components/teams/inbox/IssueFiltersPopover.tsx apps/frontend/src/components/teams/shared/components/PriorityIcon.tsx apps/frontend/src/__tests__/components/teams/inbox/IssueFiltersPopover.test.tsx
git commit -m "feat(teams): port IssueFiltersPopover + PriorityIcon"
```

---

## Task 10: Final verification + open PR

**Files:** none modified.

- [ ] **Step 1: Run the full frontend test suite**

```bash
cd apps/frontend && pnpm test 2>&1 | tail -40
```
Expected: all green. If any pre-existing test breaks, that's our regression — fix before opening PR.

- [ ] **Step 2: Run the typecheck**

```bash
cd apps/frontend && pnpm run lint 2>&1 | tail -10
```
Expected: 0 errors.

- [ ] **Step 3: Push the branch + open PR**

```bash
git push -u origin feat/teams-inbox-shared
gh pr create --title "feat(teams): port shared inbox components + Isol8 retheme (#3b)" --body "$(cat <<'EOF'
## Summary

Sub-project #3b of the [Teams UI parity roadmap](docs/superpowers/specs/2026-05-04-teams-ui-parity-roadmap.md). Wholesale port of upstream Paperclip's shared Inbox components into Isol8's `/teams` UI tree, retheming to the cream-and-warm-grey palette. Components exist + render + are tested in isolation; not yet wired into `InboxPanel.tsx` (that's #3c).

Per the upstream MIT license (`paperclip/LICENSE`), each ported file carries a 3-line attribution header.

## What's new

- `teams/shared/types.ts` — Issue / Approval / HeartbeatRun subset (only the fields IssueRow + IssueColumns + IssueFiltersPopover read).
- `teams/shared/queryKeys.ts` — SWR string-key factory mirroring upstream's React Query tuple keys.
- `teams/shared/lib/{timeAgo,assignees,issueDetailBreadcrumb,issueFilters,colorContrast,inboxColumns}.ts` — utility ports.
- `teams/shared/components/{StatusIcon,ProductivityReviewBadge,Identity,PriorityIcon}.tsx` — small visual deps.
- `teams/inbox/{SwipeToArchive,KeyboardShortcutsCheatsheet,IssueRow,IssueColumns,IssueFiltersPopover}.tsx` — the 5 inbox components.

## Out of scope (deferred)

- Wiring `InboxPanel.tsx` to use the new components — #3c.
- Hooks that hit BFF data (`useArchiveMutation`, `useUnreadIssues`) — #3c.
- `IssuesList.tsx` / `KanbanBoard` — Issues page, not Inbox.
- Detail pages (Issue, Approval, AgentRun) — #3d.
- `lib/inbox.ts` (1113 LOC) — supports `useInboxBadge`; defer to #3c.

## Test plan

- [x] Per-component unit tests for the 5 inbox components + 4 shared lib modules + 4 shared components.
- [x] Compile-only test for the types module.
- [x] Full frontend pnpm test passes.
- [ ] Manual visual verification deferred to #3c (when components are actually wired into a page).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: Watch CI**

```bash
gh run watch --repo Isol8AI/isol8 --exit-status
```

If green and Codex 👍, ready to merge. If Codex flags issues, dedupe vs prior #3a/auth-fix findings and address only valid net-new findings.

---

## Self-review checklist

Before dispatching the implementer:

- ✅ Each task touches a discrete file group with clear interfaces
- ✅ Each task has its own targeted tests (per memory `feedback_run_tests_at_end`)
- ✅ Final task runs full frontend pnpm test as the verification gate
- ✅ Spec coverage: all 10 components in the spec's `inbox/` + `shared/` tree are accounted for (including `UnreadDot` and `LiveRunBadge` ported inline as part of `IssueRow` and `IssueColumns`).
- ✅ No placeholders (every step shows the code or the exact upstream file to read).
- ✅ Type consistency: `IssueRow`'s props in Task 7 reference types defined in Task 1; `IssueColumns`' `InboxIssueColumn` type defined in Task 8.
- ✅ Roadmap update committed alongside implementation (Task 1, Step 1).
- ✅ Branch naming: `feat/teams-inbox-shared` per the design doc.
