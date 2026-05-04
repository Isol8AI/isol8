# Teams Inbox Deep Port — Design

**Status:** Spec
**Owner:** prasiddha
**Roadmap:** [Teams UI parity roadmap](./2026-05-04-teams-ui-parity-roadmap.md) — sub-project **#3 Inbox depth** (expanded scope)
**Started:** 2026-05-04

## Goal

Bring `/teams/inbox` and its surrounding detail surfaces to **full functional parity with upstream Paperclip's Inbox**, by porting the upstream code wholesale into our tree, retheming to Isol8's visual style, and translating the data layer from React Query to SWR. Same scope-of-work covers the detail pages that Inbox rows navigate into (`/teams/issues/[id]`, `/teams/approvals/[id]`, `/teams/agents/[id]/runs/[runId]`).

Originally scoped as a "tabs/filters/keyboard-nav" lift, sub-project #3 expanded after the audit revealed: (a) upstream's Inbox is 2,583 LOC plus ~10 supporting components, (b) clicking any row navigates into a detail page that's also a 40-line stub on our side, and (c) the user wants full parity, not a curated subset.

## Non-goals

- Re-deriving any upstream behaviour from scratch. The strategy is wholesale port + adapt, not redesign. (See "Wholesale port" below.)
- Adding `@tanstack/react-query` to our codebase. We translate every upstream `useQuery`/`useMutation` to SWR call sites. See "Data layer" for the patterns.
- Visual style copying. Isol8 has its own palette/typography (cream-and-warm-grey from `/chat`); ported components retheme on the way in.
- Behaviour changes vs. upstream. If upstream's Inbox does X, our port does X. Differences live only at the boundaries: auth, routing, theme.
- Multi-tenant board admin features that don't apply to our model (Isol8 is single-user-per-container; org users share one container).
- Workspaces / ExecutionWorkspace surface. Out of scope for #3 even though Paperclip's IssueRow surfaces a workspace pill — we'll render a no-op or omit the pill where it would otherwise dead-link. Workspaces become its own sub-project later (the user noted Isol8's per-user EFS may map naturally onto this concept).

## Background

`/teams` shipped in PR #509 as a tier-1 minimal port. The Inbox panel is 49 lines; upstream's is 2,583. Sub-project #1 (Realtime, PR #518) just shipped the WS pipeline that lets any panel receive live events. With realtime in place, the next priority is making the panels themselves substantive — and Inbox is the daily entry point.

Upstream Paperclip is **MIT-licensed** (`paperclip/LICENSE`); porting requires retaining the copyright notice in each ported file's header. No other restrictions.

## Wholesale port: what that actually means

"Port" here means **copy each upstream file, translate the boundaries (auth, routing, data layer, theme), keep the rest verbatim**. Specifically:

- **What stays verbatim:** business logic, JSX structure, component composition, prop shapes, state machines (e.g. archive-fade-undo), keyboard handlers, derived-state hooks, types/schemas/zod validators, query-key namespacing.
- **What translates:** `useQuery(...)` → `useTeamsApi().read(...)`, `useMutation` → `await api.post(...); mutate(key)`, `queryClient.invalidateQueries(...)` → `useSWRConfig().mutate(key)`, React Router → Next App Router, Paperclip Tailwind tokens → Isol8 palette, Better-Auth session direct → BFF-mediated session cookie (already plumbed via `paperclip_user_session`).
- **What gets dropped:** any feature that's marked "skip — not applicable to Isol8" in the gap audit (multi-tenant board admin, etc.).

Each ported file's first three lines:
```
// Ported from upstream Paperclip <github URL> (MIT, © 2025 Paperclip AI).
// Retheme to Isol8 palette + SWR data layer. See spec at
// docs/superpowers/specs/2026-05-04-teams-inbox-deep-port-design.md
```

## Architecture

```
apps/frontend/src/components/teams/
├── inbox/                              # ports of upstream Inbox + supporting components
│   ├── InboxPage.tsx                   # ports paperclip/ui/src/pages/Inbox.tsx
│   ├── IssueColumns.tsx                # ports paperclip/ui/src/components/IssueColumns.tsx
│   ├── IssueRow.tsx                    # ports paperclip/ui/src/components/IssueRow.tsx
│   ├── IssuesList.tsx                  # ports paperclip/ui/src/components/IssuesList.tsx
│   ├── IssueFiltersPopover.tsx         # NEW; extracted from Inbox.tsx
│   ├── KeyboardShortcutsCheatsheet.tsx
│   ├── SwipeToArchive.tsx
│   ├── UnreadDot.tsx
│   ├── LiveRunBadge.tsx
│   └── hooks/
│       ├── useArchiveMutation.ts
│       ├── useUnreadIssues.ts
│       └── useInboxKeyboardShortcuts.ts
├── issues/
│   ├── IssueDetailPage.tsx             # ports paperclip/ui/src/pages/IssueDetail.tsx
│   ├── IssueComments.tsx
│   └── IssueRunTranscript.tsx
├── approvals/
│   └── ApprovalDetailPage.tsx          # ports paperclip/ui/src/pages/ApprovalDetail.tsx
├── runs/
│   └── AgentRunPage.tsx                # ports paperclip's run-detail surface
├── shared/
│   ├── types.ts                        # Issue, Approval, HeartbeatRun, JoinRequest types
│   ├── schemas.ts                      # zod validators (if upstream uses them)
│   └── queryKeys.ts                    # SWR cache keys ↔ upstream queryKeys mapping
└── panels/
    └── InboxPanel.tsx                  # becomes a 1-line wrapper around <InboxPage />

apps/frontend/src/app/teams/
├── inbox/page.tsx                      # renders <InboxPage>
├── issues/[issueId]/page.tsx           # replaces 40-line stub with <IssueDetailPage>
├── approvals/[approvalId]/page.tsx     # replaces stub
└── agents/[agentId]/runs/[runId]/page.tsx  # NEW route or replaces stub

apps/backend/routers/teams/
├── inbox.py                            # MAJOR EXPAND from 49 lines: ?tab=, filters
├── issues.py                           # EXPAND: full Issue + comments + linked runs
├── approvals.py                        # EXPAND: full Approval detail
├── runs.py                             # NEW: agent run detail
├── members.py                          # EXPAND: members list for assignee dropdowns
├── projects.py                         # NEW: project list for filter dropdown
└── workspaces.py                       # NEW (placeholder): workspace pills
```

## 4-PR phased delivery

Each PR ships working end-to-end. The user reverses on "one giant PR" mid-brainstorm because 4 weeks in one branch is review-hostile and merge-risky.

| # | PR title | Branch | Scope |
|---|---|---|---|
| **#3a** | feat(teams): backend BFF endpoints for inbox + detail surfaces | `feat/teams-inbox-bff` | All `/teams/{inbox,issues,approvals,runs,members,projects,workspaces}` BFF routes. Pure backend; UI unchanged. |
| **#3b** | feat(teams): shared inbox components + Isol8 retheme | `feat/teams-inbox-shared` | Port shared components (IssueRow, IssueColumns, IssuesList, hooks, types/schemas, queryKeys). React Query → SWR translation patterns established. Frontend-design subagent retheme to Isol8 palette. Components exist; not yet wired. |
| **#3c** | feat(teams): port Inbox page with full Paperclip parity | `feat/teams-inbox-page` | Replace 49-line `InboxPanel` with `<InboxPage>`. Tabs, filters, search, keyboard nav, archive/undo, mark-read, live badges, swipe-to-archive. Click → `/teams/issues/[id]` (still stub at end of #3c). |
| **#3d** | feat(teams): port IssueDetail + ApprovalDetail + AgentRun pages | `feat/teams-inbox-details` | Replace stub detail pages with full ports. Comments, transcripts, status mutations, run telemetry. |

Cumulative effort: ~4 weeks. Independent revertibility per PR.

## Backend BFF endpoints (#3a)

Each route follows the existing pattern: receive Clerk auth → `_ctx` Depends → mint per-user Paperclip session cookie via `paperclip_user_session` → forward verbatim to upstream Paperclip → return response body unmodified.

**New / expanded routes:**

| Method + Path | Forwards to | Notes |
|---|---|---|
| `GET /teams/inbox?tab=mine\|recent\|all\|unread&search=&status=&project=&assignee=&creator=&limit=` | `GET /api/companies/{co}/issues` (with same query) | Replace current 49-line stub. Pass tab + filters through. |
| `GET /teams/inbox/approvals` | `GET /api/companies/{co}/approvals` | NEW |
| `GET /teams/inbox/runs` | `GET /api/companies/{co}/heartbeat-runs?status=failed` | NEW |
| `GET /teams/inbox/joins` | `GET /api/companies/{co}/join-requests` | NEW (only if upstream surfaces this) |
| `GET /teams/inbox/live-runs` | `GET /api/companies/{co}/live-runs` | NEW; data source for live badges |
| `POST /teams/inbox/{id}/archive` | `POST /api/companies/{co}/issues/{id}/archive` | NEW |
| `POST /teams/inbox/{id}/unarchive` | `POST /api/companies/{co}/issues/{id}/unarchive` | NEW; for undo |
| `POST /teams/inbox/{id}/mark-read` | `POST /api/companies/{co}/issues/{id}/mark-read` | NEW |
| `POST /teams/inbox/{id}/mark-unread` | `POST /api/companies/{co}/issues/{id}/mark-unread` | NEW |
| `GET /teams/issues/{id}` | `GET /api/companies/{co}/issues/{id}` | EXPAND from current shape |
| `GET /teams/issues/{id}/comments` | `GET /api/companies/{co}/issues/{id}/comments` | NEW |
| `POST /teams/issues/{id}/comments` | `POST /api/companies/{co}/issues/{id}/comments` | NEW |
| `PATCH /teams/issues/{id}` | `PATCH /api/companies/{co}/issues/{id}` | NEW; status/priority/assignee mutations |
| `GET /teams/approvals/{id}` | `GET /api/companies/{co}/approvals/{id}` | EXPAND |
| `POST /teams/approvals/{id}/approve` | upstream | NEW |
| `POST /teams/approvals/{id}/reject` | upstream | NEW |
| `GET /teams/runs/{id}` | `GET /api/companies/{co}/heartbeat-runs/{id}` | NEW |
| `POST /teams/runs/{id}/retry` | upstream | NEW |
| `GET /teams/members` | `GET /api/companies/{co}/members` | EXPAND |
| `GET /teams/projects` | `GET /api/companies/{co}/projects` | NEW |
| `GET /teams/workspaces` | `GET /api/companies/{co}/workspaces` | NEW (placeholder; data source for IssueRow's workspace pill) |

**No aggregation, no caching at the BFF.** Each route is a thin forward. Where upstream returns paginated lists, we forward the cursor verbatim.

**Auth model unchanged.** All routes go through the existing `_ctx` Depends helper that resolves Clerk → per-user Paperclip session cookie.

## Frontend data layer (#3b)

Translation patterns codified once in `apps/frontend/src/components/teams/shared/queryKeys.ts`:

```ts
// Mirror of paperclip/ui/src/lib/queryKeys.ts. Same namespace, same shape,
// translated to SWR keys. Each upstream queryKeys.foo(args) returns a
// React Query tuple key; ours returns a string SWR key.
export const queryKeys = {
  inbox: {
    list: (tab: InboxTab, filters: InboxFilters) =>
      `/teams/inbox?tab=${tab}&${qs(filters)}`,
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
};
```

**Pattern translations:**

| Upstream (React Query) | Our port (SWR) |
|---|---|
| `useQuery({ queryKey: queryKeys.inbox.list(tab), queryFn: ..., refetchInterval: 30000 })` | `read(queryKeys.inbox.list(tab), { refreshInterval: 30000 })` |
| `useMutation({ mutationFn: archiveIssue, onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.inbox }) })` | `await post('/teams/inbox/{id}/archive'); mutate(key => key.startsWith('/teams/inbox'))` |
| Optimistic update via `onMutate` + rollback in `onError` | `mutate(key, (cur) => cur.filter(...), { revalidate: false, rollbackOnError: true })` |
| `queryClient.cancelQueries({ queryKey })` | (no equivalent needed; SWR auto-cancels via stale revalidation) |
| `queryClient.getQueryData(queryKey)` | `cache.get(key)` via `useSWRConfig().cache` |
| `keepPreviousData` | `keepPreviousData: true` (SWR has this) |
| `useInfiniteQuery` | `useSWRInfinite` (Inbox doesn't currently use infinite scroll, but be aware) |

**Realtime integration** (extends #518):

`TeamsEventsProvider` already handles SWR invalidation for `teams.activity.logged`, `teams.agent.status`, `teams.heartbeat.run.*`. We extend its `EVENT_KEY_MAP` to invalidate the new fine-grained keys (e.g. `/teams/issues/${id}` on `activity.logged` if the event payload's issue id matches).

For the live-runs badge, `teams.heartbeat.run.queued/status` events will already invalidate `/teams/inbox/live-runs` once we add it to the map.

## Visual retheme (#3b + #3c + #3d)

Upstream uses Paperclip's Tailwind config: cool blues, system-default typography, shadcn-default surfaces. Isol8 uses cream-and-warm-grey palette + sophisticated typography from `/chat` and the landing page.

**Approach:** every ported component goes through a frontend-design subagent pass that:
1. Reads the existing Isol8 reference (`/chat` panels, `/settings` cards, `landing` typography).
2. Maps Paperclip's Tailwind tokens onto Isol8's palette equivalents:
   - `bg-blue-500` → `bg-amber-700` (or whatever the right Isol8 accent is)
   - `text-zinc-500` → Isol8's warm-grey-secondary token
   - `border-zinc-200` → Isol8's cream-border
   - shadcn `Card` → keep the shadcn primitives but with Isol8-themed CSS variables
3. Verifies typography matches (font weights, line heights, spacing rhythm).
4. Preserves all upstream interaction patterns (hover states, focus rings, transitions).

This is component-by-component, not a sweeping replace-all script. Each subagent handles one component file.

## Routing (Next App Router)

Upstream's React Router paths translate to Next App Router pages:

| Upstream | Our port |
|---|---|
| `/inbox` | `/teams/inbox/page.tsx` |
| `/issues/[id]` | `/teams/issues/[issueId]/page.tsx` |
| `/approvals/[id]` | `/teams/approvals/[approvalId]/page.tsx` |
| `/agents/[id]/runs/[runId]` | `/teams/agents/[agentId]/runs/[runId]/page.tsx` |

Each page file: `'use client'` directive at top, render the ported component, pass route params via `useParams()`. Same wrap as existing /teams routes.

**Inbox row click navigation:** uses Next's `<Link>` component with `href={\`/teams/issues/${issue.id}\`}`. Upstream's `createIssueDetailLocationState()` (which preserved Inbox scroll position via React Router state) translates to Next's `router.push(href, { scroll: false })` plus a small custom scroll-restoration hook on the Inbox page that records position to sessionStorage on unmount.

## Auth wiring

Already solved by sub-project #0 (PR #509) — `_ctx` Depends helper in BFF mints per-user Paperclip session cookie via `paperclip_user_session`. New BFF routes inherit the same pattern. No new auth code.

## Realtime integration

#518's `TeamsEventsProvider` already mounted in `TeamsLayout`. We extend its `EVENT_KEY_MAP`:

```tsx
const EVENT_KEY_MAP = {
  // ... existing entries from #518 ...
  "teams.activity.logged": [
    "/teams/dashboard", "/teams/activity",
    "/teams/inbox?tab=mine", "/teams/inbox?tab=recent",
    "/teams/inbox?tab=all",
    "/teams/inbox/approvals",
    "/teams/issues",  // not key-prefix-aware in SWR; we'll match by predicate
  ],
  "teams.heartbeat.run.queued": [
    /* existing */, "/teams/inbox/live-runs", "/teams/inbox/runs",
  ],
  // ... new entries for the new endpoints
};
```

SWR's `mutate(key)` doesn't natively support prefix matching, so for endpoints like `/teams/issues/{id}` (one cache key per id), we use `mutate((cacheKey) => typeof cacheKey === 'string' && cacheKey.startsWith('/teams/issues'))` — SWR supports a predicate function as the key argument.

## Error handling

| Failure | Behaviour |
|---|---|
| BFF returns 4xx | SWR throws; component catches via `error` from `read(...)`. Each panel has an error state UI. |
| BFF returns 5xx | Same as 4xx; SWR retries per `errorRetryInterval` config. |
| Upstream Paperclip returns 4xx | BFF forwards verbatim; UI handles. |
| Optimistic mutation fails | SWR's `rollbackOnError: true` reverts cache. Show toast (when toast library exists; for now, log + browser alert acceptable in v1). |
| WS event arrives for an issue not in current Inbox view | Invalidation fires anyway; SWR refetches; if no longer relevant, no-op. |
| Per-user Paperclip session cookie expired | Existing `paperclip_user_session` re-mints on 401 (already handled). |

## Testing

**Per-PR scope:**

| PR | Tests |
|---|---|
| #3a | Backend: unit tests per BFF route asserting auth, query-param forwarding, response pass-through. moto for any DDB-touching path. ~20-30 backend tests added. |
| #3b | Frontend unit: per shared component (IssueRow, IssueColumns, IssuesList, hooks). Mock SWR + assert render output / interaction handlers. ~15-20 frontend tests added. |
| #3c | Frontend unit: InboxPage end-to-end with mocked BFF. Assert tab switching, filter application, archive flow with optimistic update + rollback, keyboard shortcut firing. ~10-15 frontend tests. |
| #3d | Frontend unit: each detail page with mocked BFF. Assert mutations land + invalidate correctly. ~10 frontend tests. |

**No E2E** for any of them — Playwright is too brittle for this surface. Unit + integration coverage at each layer plus manual dev verification is the right level.

**Visual regression:** none. Frontend-design subagent does style review at port time.

## Acceptance criteria

After all 4 PRs are merged:

1. `/teams/inbox` shows tabs (Mine / Recent / All / Unread) with count badges that update live as upstream events fire.
2. Filtering by status, project, assignee, creator, search text — all work; filters persist in URL query params.
3. Keyboard shortcuts: `j/k` selection, `Enter` open, `a/y` archive, `r` mark-read, `?` cheatsheet, `/` search-focus.
4. Archive a row → fades over 300ms, removes from list, undo toast appears for 8s; `Ctrl+Z` restores.
5. Click an issue row → navigates to `/teams/issues/[id]` showing full detail page with comments, status mutation, run transcripts.
6. Approval row's Approve/Reject buttons fire mutations + invalidate inbox.
7. Failed run row's Retry button fires mutation + shows fresh status via realtime.
8. Live runs badge appears on issues with active runs; pulses; updates on `heartbeat.run.queued/status` events.
9. Mobile layout: full-width search, stacked actions; SwipeToArchive works.
10. Visual: color palette matches Isol8's `/chat` cream-and-warm-grey. Typography matches existing Isol8 spec.

## Rollout

**Per-PR replacement, no feature flag.** Each PR is small enough that revert is the rollback. Phased delivery already de-risks; adding a flag to a 4-PR sequence adds complexity without proportional benefit.

After #3a merges: pure backend, no UI change. After #3b: shared components built but unused. After #3c: Inbox flips to full Paperclip parity; clicks land on stub detail pages (current behavior). After #3d: whole loop closes.

If anything breaks at #3c, revert #3c restores the 49-line stub. If something breaks at #3d, revert #3d leaves a working Inbox + stub details (current shipped state on main).

## Out of scope

These are upstream Inbox features we deliberately don't port for #3:

- **Multi-tenant board admin views** (e.g. impersonation, all-tenants list). Isol8 is single-user-per-container; doesn't apply.
- **Workspaces / ExecutionWorkspace surface.** The IssueRow's workspace pill renders a no-op (or omits) until the user's separate "workspace" sub-project lands.
- **PluginPage / PluginSettings hooks** in Inbox (some upstream Inbox rows can deep-link to plugin UIs). Isol8 doesn't expose plugins; render the row without the plugin link.
- **`/onboarding` / company-creation flows** triggered from empty-inbox states. Isol8 has its own onboarding (Clerk + provisioning); use Isol8's empty-state copy.
- **CommandPalette integration.** Sub-project #4 in the roadmap; out of scope here.

## License retention

Each ported file's first three lines (per the wholesale-port commitment):

```
// Ported from upstream Paperclip <github URL> (MIT, © 2025 Paperclip AI).
// Retheme to Isol8 palette + SWR data layer. See spec at
// docs/superpowers/specs/2026-05-04-teams-inbox-deep-port-design.md
```

Plus one root-level `THIRD_PARTY_NOTICES.md` (or addition to the existing one if present) crediting Paperclip with link to upstream + license text.

## Risk assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Upstream Paperclip API drift mid-port | Medium | Medium — breaks ported components | Pin against current Paperclip checkout (already vendored at `paperclip/`). Revisit in 6 months. |
| BFF auth translation bug for new routes | Low | High — leaks data cross-tenant | All routes use existing `_ctx` Depends; pattern is proven in #509. |
| Optimistic update rollback bugs | Medium | Low — UI flicker | Per-mutation tests assert rollback path. |
| Visual retheme incomplete (some Paperclip token missing in Isol8) | Medium | Low — visual fallback ugly | Frontend-design subagent flags missing tokens; we extend Isol8's Tailwind config if needed. |
| One PR (e.g. #3c) takes longer than estimated | High | Low — phasing absorbs slippage per-PR | Each PR is independently shippable; longer PR doesn't block others (sequential, not parallel). |
| MIT license header forgotten on some files | Low | Medium — license violation | Pre-merge spec-reviewer subagent checks header on every ported file. |

## Decision log

- **MIT license + wholesale port (not vendor as dependency)**: Paperclip is MIT, allows free port. Vendoring as a dependency would require keeping their build system, Vite config, theme — way more friction than copying files.
- **SWR (not adding React Query)**: 1-2 days of translation cost vs. dual-cache complexity + bundle weight. SWR wins.
- **4-PR phasing (not one giant PR)**: 4 weeks in one branch is review-hostile; phasing already de-risks; user reversed mid-brainstorm.
- **No feature flag**: replacement is simpler; per-PR revert is the rollback path.
- **Drop "drawer" idea**: upstream uses full-page detail nav; matching upstream means matching this. Drawer pattern was a scope-cut idea before user clarified "full parity".
- **Workspaces deferred**: per user note, Isol8's per-user EFS may map onto workspace concept; deserves its own sub-project later.
