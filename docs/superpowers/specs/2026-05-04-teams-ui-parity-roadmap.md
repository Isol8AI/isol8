# Teams UI Parity Roadmap

**Status:** Active
**Owner:** prasiddha
**Started:** 2026-05-04

## Background

The native `/teams` UI shipped in PR #509 as a "tier-1 minimal" port of the upstream Paperclip UI it replaced (the previous transparent reverse proxy of `dev.company.isol8.co`). Tier-1 was 17 panels covering the core CRUD surfaces. Upstream Paperclip has ~67 page files. After landing the lazy-provisioning fix in PR #514 (so existing personal users actually reach `/teams`), it became visible that several core panels feel sparse vs. what upstream provides — particularly Inbox, Dashboard, and AgentDetail — and that the whole UI lacks live updates.

A gap audit produced this prioritized list of sub-projects to close the most-visible gaps. Each gets its own brainstorm → spec → plan → PR cycle. This file is the single source of truth for what's next; individual specs link back here.

## Sub-projects

| # | Sub-project | Effort | Status | Spec | Plan | PR |
|---|---|---|---|---|---|---|
| 1 | Realtime updates (BFF WS subscriptions + frontend hook for live badges, agent status dots, run progress, dashboard counts) | L | Plan | [2026-05-04-teams-realtime-design.md](./2026-05-04-teams-realtime-design.md) | [2026-05-04-teams-realtime.md](../plans/2026-05-04-teams-realtime.md) | — |
| 2 | Dashboard charts (4 live charts: run activity, success rate, issue status, priority breakdown; recent activity panel) | M | Pending | — | — | — |
| 3 | Inbox depth (tabs All/Mine/Approvals, filters, detail drawer, archive/undo, keyboard nav) | M | Pending | — | — | — |
| 4 | Command palette (cmd+k for fast nav/search/create across agents/issues/projects) | S | Pending | — | — | — |
| 5 | Agent org chart (new panel: agent hierarchy viz with reports_to + live status dots) | L | Pending | — | — | — |

## Dependency graph

```
#1 Realtime  ──┬──> #2 Dashboard charts (live counters)
               ├──> #3 Inbox depth (live badges)
               └──> #5 Org chart (live status dots)

#4 Command palette: independent, can ship anytime
```

Recommended execution order: **#1 first** (foundational), then **#2 + #3 in parallel** (different panels, different reviewers), then **#4** and **#5** in either order.

## Status legend

- **Pending** — backlog; no spec or plan yet.
- **Brainstorming** — design discussion in progress; spec not yet committed.
- **Spec** — design committed; plan not yet written.
- **Plan** — implementation plan committed; PR not yet open.
- **In progress** — PR open; subagent execution in flight.
- **Done** — PR merged.

## Out of scope (for now)

The gap audit identified pages that we deliberately won't port:

- **Admin/operator surfaces:** AdapterManager, PluginManager, InstanceSettings, InstanceGeneralSettings, InstanceExperimentalSettings, CompanyImport/Export, CompanyEnvironments — Paperclip exposes these to instance admins; they're operator concerns, not tenant concerns.
- **Already covered elsewhere:** ProfileSettings (Clerk UserButton + `/settings` in Isol8), UserProfile, Auth/CliAuth/BoardClaim/InviteLanding (handled by Clerk + `/onboarding`).
- **Doesn't fit our model:** Workspaces, ExecutionWorkspaceDetail, ProjectWorkspaceDetail (Isol8 maps workspace → per-user container; no multi-workspace concept), JoinRequestQueue (Isol8 is single-tenant per user, not multi-tenant), CompanyEnvironments (single per-user container).
- **Folded into existing entities:** Goals/GoalDetail (Isol8 folds goal-like work into Issues; no separate entity).

If priorities shift and one of these does become important, add it as a new row above with status `Pending` rather than starting a parallel roadmap.

## Convention

- Each sub-project's spec filename: `docs/superpowers/specs/YYYY-MM-DD-teams-<short-name>-design.md` (e.g. `2026-05-04-teams-realtime-design.md`).
- Each sub-project's plan filename: `docs/superpowers/plans/YYYY-MM-DD-teams-<short-name>.md`.
- When a sub-project enters Brainstorming/Spec/Plan/In-progress, update its row above (status + link).
