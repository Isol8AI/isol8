# Cron Panel: View, Edit, and Vet

**Date:** 2026-04-14
**Status:** Draft

## Problem

The Crons tab in the control dashboard shows cron jobs but omits almost everything useful for operating them:

- **The prompt is hidden.** Users can't see what each cron actually asks the agent to do without opening the edit form.
- **Run output is invisible.** Only a truncated 2000-char `summary` string is shown; the full agent transcript — messages, tool calls, errors — cannot be inspected. This makes it impossible to answer "what did my cron actually do last time?"
- **Rich OpenClaw capabilities are unused.** Per-run tokens, model used, delivery status, error classification, and session IDs all come back on `cron.runs` today but are not rendered. Per-job `delivery`, `failureAlert`, `timeoutSeconds`, `toolsAllow`, `model` / `fallbacks`, and `deleteAfterRun` are settable via `cron.update` but not exposed in our form.
- **Delivery configuration is completely absent.** Users can't set or change where a cron's output goes (chat announcement, Telegram, Discord, webhook), so crons are effectively blind unless users peek into OpenClaw config directly.

Users want to be able to **view, edit, and vet** their cron jobs from this page.

## Design

### Two-state UI

The Crons panel has two UI states. Transitions are driven by user interaction; no routing changes.

**State A — Jobs overview (default)**

Single-column list of job cards, one per cron job. Each card:

- Header: name, status pill (`active` / `paused` / `error`), kebab (Edit · Pause/Resume · Run now · Delete).
- Metadata line: formatted schedule · next run (relative) · last run badge (color-coded by `state.lastRunStatus`) · delivery summary (e.g. "Delivers to: Telegram @me").
- **Prompt preview**: first ~200 chars of `payload.message`, truncated with ellipsis, full text on hover.
- Optional description below prompt preview (small, muted).
- Collapsible "Recent runs (10)" section — same inline expand pattern as today. Each run row shows status dot, relative time, duration, delivery ✓/✗, truncated summary. Clicking a run transitions to State B.
- **Running indicator**: if `state.runningAtMs` is set, the card pulses and a "Running now…" line appears alongside the next-run countdown (the two are independent — `nextRunAtMs` is the next scheduled fire, not gated on the current run).

Header actions: `+ New cron` button at the top.

**State B — Run vetting (drilled in)**

Triggered by clicking a run row in any expanded card in State A. Layout becomes a two-column master/detail inside the control panel area:

- Top bar: `← Back to jobs` · job name · `(deleted)` badge if the job no longer exists.
- **Left column**: runs for this specific job (scoped, not cross-job). Filter bar (status: all/ok/error/skipped; date range; free-text search over `summary` and `error`). Paginated via `cron.runs` offset/limit. Load-more button.
- **Right column**: selected run's detail panel.

Navigation between State B runs happens by clicking another row in the left column — only the right panel updates. Returning to State A: the back button, or the X in the right panel header.

Layout shift visually mirrors `FileViewer` (`ChatLayout.tsx:202`, `.with-file-viewer` grid pattern): the control panel grid gets a second column when entering State B, not an overlay.

### Run detail panel (State B right)

Top to bottom:

- **Header row**: status pill, absolute timestamp, duration, actions (`Run this job now`, `Edit job`, `Copy prompt`), close X.
- **Error block** (error runs only): red alert with `lastErrorReason` category and full `error` text.
- **Prompt** (collapsible, default collapsed): full `payload.message`. If the run's transcript is available, the prompt block is populated from the session's first user message (which reflects the actual prompt sent at run time), not from the current `job.payload.message`, since the job may have been edited since the run. Falls back to the current job prompt if the transcript is unavailable.
- **Transcript**: fetched via the session RPC (see Data flow) using `runEntry.sessionId`. Rendered with a read-only variant of `MessageList` — the existing chat-transcript component with the input bar removed, auto-scroll-to-bottom disabled, and thinking animations frozen. Markdown, tool-event rendering, and code blocks are reused as-is.
- **Run metadata**:
  - Model (and fallback index if a fallback was used).
  - Tokens: input, output, cache-read, cache-write (each hidden when zero).
  - Delivery: status (✓/✗), target, delivery error if present.
  - Session ID (truncated).
  - Next run timestamp for the parent job.

Loading state for transcript: skeleton. Missing `sessionId`: "No transcript available for this run." Fetch error: banner + retry, metadata still renders.

### Edit form

Modal dialog, reusing the existing edit-dialog pattern. Sections are collapsible accordions; Basics and Delivery open by default, the rest closed.

**1. Basics** *(open)*
- `name` — text.
- `description` — textarea, optional. Labeled "Notes for you" to distinguish from the prompt.
- `enabled` — checkbox.
- `schedule` — kind picker (`at` | `every` | `cron`) with kind-specific inputs. Cron expression gets a live "next 3 fires" preview. Timezone dropdown for `cron`. Interval + unit for `every`. Timezone-aware datetime-local for `at`.
- `prompt` — textarea, maps to `payload.message`. Labeled "Prompt sent to agent".

`payload.kind` is fixed to `"agentTurn"` — not exposed. `sessionTarget` is fixed to `"isolated"` — not exposed. The frontend currently hard-codes both (`CronPanel.tsx:441,443`), and OpenClaw's agent-facing cron tool defaults to the same (`cron-tool.ts:465`, `:495`), so ~100% of Isol8 crons are isolated agent-turns. This spec maintains that invariant.

**2. Delivery** *(open)*
- `delivery.mode` — segmented: `None` · `Announce` · `Webhook`.
- If `Announce`:
  - `channel` — dropdown populated from `channels.status`, showing only enabled channels plus a synthetic "Chat (this session)" option meaning `channel` is unset and announce goes into the isolated session's own announce stream.
  - `accountId` — dropdown populated from the selected channel's accounts; hidden if only one account exists.
  - `to` — text, per-channel help (Telegram: `@handle` or chat ID; Discord: `#channel`; etc.).
  - `threadId` — text, shown only if selected channel supports threads/topics.
  - `bestEffort` — checkbox: "Don't mark run as error if delivery fails."
- If `Webhook`:
  - `to` — URL input.
- **Failure destination** sub-section (collapsed): same channel/account/to/mode picker, labeled "Where to send failure notifications (if different)."

**3. Agent execution** *(collapsed)*
- `payload.model` — reuses `ModelSelector`; "Use agent default" is the implicit null.
- `payload.fallbacks` — ordered multi-select of models (drag-to-reorder), same picker.
- `payload.timeoutSeconds` — number input, blank = default.
- `payload.toolsAllow` — multi-select from `tools.list { agentId }`. Empty = all tools allowed; help text makes this explicit.
- `payload.thinking` — text input (advanced).
- `payload.lightContext` — checkbox.

**4. Failure alerts** *(collapsed)*
- Enabled checkbox — off writes `failureAlert: false`; on reveals the rest.
- `after` — number, default 3.
- `channel` / `accountId` / `to` / `mode` — same picker as delivery.
- `cooldownMs` — number + unit picker, default 60 min.

**5. Advanced** *(collapsed)*
- `deleteAfterRun` — checkbox with warning.
- `wakeMode` — segmented: `next-heartbeat` · `now`.
- `agentId` — reuses existing agent picker; defaults to current agent.

Footer: Cancel / Save. Save calls `cron.update` (patch) for edit, `cron.add` for create. Create defaults: `enabled: true`, `schedule: every 1 day`, `delivery.mode: "announce"` with channel auto-picked (chat if none enabled, else first enabled channel), `sessionTarget: "isolated"`, `wakeMode: "next-heartbeat"`, `payload.kind: "agentTurn"`.

Validation is inline; schedule preview shown before save. Destructive actions (delete, toggling `deleteAfterRun`) get confirm dialogs.

### Data flow

| Surface | RPC | When | Cache strategy |
|---|---|---|---|
| Job list (State A) | `cron.list { includeDisabled: true, limit: 100 }` | Panel mount; mutate after add/update/remove/run | SWR, revalidate on focus, 30s poll while visible |
| Inline recent runs (State A expand) | `cron.runs { scope: "job", id, limit: 10 }` | Expand click | SWR |
| Runs list (State B) | `cron.runs { scope: "job", id, limit: 50, statuses?, query?, ... }` + paged load-more | Enter State B; filter change | SWR, keyed by (jobId, filters) |
| Run transcript (State B right) | Sessions RPC (TBD: `sessions.resolve` per earlier research; confirmed in plan step 1) | Select run | SWR, keyed by sessionId |
| Delivery channel options | `channels.status {}` | Open edit form | SWR, 1-min stale |
| Tools allowlist options | `tools.list { agentId }` | Open edit form; agent change | SWR, keyed by agentId |
| Model options | existing `models.list` used by `ModelSelector` | Open edit form | reuse existing |

Mutations via `useGatewayRpcMutation`. Optimistic update on the enabled toggle; otherwise server-confirmed.

No backend changes. All RPCs pass through `container_rpc.py`'s generic WebSocket passthrough.

### Types

Extend the frontend to match OpenClaw's full model. Extract types out of `CronPanel.tsx` (currently ~700 lines) into `apps/frontend/src/components/control/panels/cron/types.ts`.

**`CronJob`** additions to the frontend type:
- `delivery?: CronDelivery` with `{ mode, channel?, to?, threadId?, accountId?, bestEffort?, failureDestination? }`.
- `failureAlert?: CronFailureAlert | false`.
- `deleteAfterRun?: boolean`.
- `sessionTarget: CronSessionTarget` (kept on the type for read compatibility with pre-existing non-isolated jobs; hard-coded `"isolated"` on all writes).
- `wakeMode: CronWakeMode`.
- `payload` extended with `model?`, `fallbacks?`, `thinking?`, `timeoutSeconds?`, `toolsAllow?`, `lightContext?`, `allowUnsafeExternalContent?`.
- `state` extended with `runningAtMs?`, `lastErrorReason?`, `consecutiveErrors?`, `lastFailureAlertAtMs?`, `lastDeliveryStatus?`, `lastDeliveryError?`, `lastDelivered?`.

**`CronRunEntry`** additions:
- `sessionId?`, `sessionKey?`.
- `model?`, `provider?`.
- `usage?: { input_tokens?, output_tokens?, total_tokens?, cache_read_tokens?, cache_write_tokens? }`.
- `deliveryStatus?`, `deliveryError?`, `delivered?`.

Field names and shapes match `/Users/prasiddhaparthsarthy/Desktop/openclaw/src/cron/types.ts` and `types-shared.ts` exactly, so the frontend can safely forward the full object to `cron.update` as a patch without translation.

### File layout

Current `CronPanel.tsx` (~700 lines) is split into focused units. Each has one clear purpose and can be understood in isolation:

```
apps/frontend/src/components/control/panels/
├── CronPanel.tsx                       # container; state machine (A↔B); SWR wiring
└── cron/
    ├── types.ts                        # extracted types matching OpenClaw
    ├── JobCard.tsx                     # State A card
    ├── JobList.tsx                     # State A list + empty state
    ├── JobEditDialog.tsx               # modal shell
    ├── JobEditSections.tsx             # accordion sections (Basics/Delivery/…)
    ├── DeliveryPicker.tsx              # channel/account/to/threadId composite
    ├── ToolsAllowlist.tsx              # multi-select backed by tools.list
    ├── SchedulePicker.tsx              # at/every/cron with live preview
    ├── RunList.tsx                     # State B left column
    ├── RunListRow.tsx                  # individual run row
    ├── RunFilters.tsx                  # status/date/query bar
    ├── RunDetailPanel.tsx              # State B right column container
    ├── RunTranscript.tsx               # read-only MessageList wrapper
    └── RunMetadata.tsx                 # model/tokens/delivery block
```

State machine inside `CronPanel.tsx`:

```ts
type ViewState =
  | { kind: "overview" }                                          // State A
  | { kind: "runs"; jobId: string; selectedRunTs: number | null } // State B
```

Run rows are keyed by `jobId + triggeredAtMs` — OpenClaw's `CronRunLogEntry` has no explicit run id.

### Edge cases

- **Cron currently running** (`state.runningAtMs` set): card pulses; in State B, a synthetic "in-progress" row appears at the top of the runs list.
- **Missing `sessionId` on older runs**: right panel transcript shows "No transcript available for this run"; metadata still renders.
- **Session fetch errors**: right panel shows error banner with retry; metadata still renders.
- **Job self-deletes (`deleteAfterRun`)**: card disappears from State A on next `cron.list` revalidate. In State B on a deleted job: `(deleted)` badge in breadcrumb, runs still readable from JSONL, edit/run-now actions disabled.
- **User deletes job while viewing its runs**: toast "Cron deleted"; auto-return to State A.
- **Many runs**: left column paginates via `cron.runs` offset/limit. OpenClaw's JSONL prunes to ~2000 lines, so the total is naturally bounded.
- **Delivery failed but run succeeded**: status pill stays green; delivery block in metadata shows "✗ Delivery failed: {deliveryError}". Execution and delivery outcomes are visually independent.
- **Container asleep (free tier scale-to-zero)**: first RPC call triggers cold start; the existing `useGateway` connection-state UI handles the "Waking your agent…" banner globally — no panel-specific code.
- **No agents yet**: disables `+ New cron`, shows "Create an agent first" helper.
- **Invalid cron expression**: live validation on the field; save disabled until valid.
- **Pre-existing non-`isolated` jobs** (e.g., created via CLI): render normally; edit form doesn't expose `sessionTarget`; `cron.update` is a patch so the field is preserved on save.
- **Job prompt edited after run**: when the transcript is available, the prompt block reads the session's first user message (what was actually sent), not the current job prompt.

### Error banners

- `cron.list` fails: banner at top of panel with retry.
- `cron.runs` fails: banner in the run list (State B left or State A inline).
- Mutation errors: inline toast with server error text.

## Non-goals (v1)

- Cross-job "global runs inbox" view. State B is scoped to one job.
- Editing `sessionTarget` / `payload.kind` in the form. Both are fixed to their current implicit defaults.
- A route change or deep-linkable URL per run. Everything lives inside the existing control-panel area.
- Run-time snapshotting of the prompt in the run log. OpenClaw doesn't persist it; we read the session's first user message instead when available.
- A dedicated "log export" or "download transcript" feature.

## Open items resolved in the plan

- Confirm the exact sessions RPC name and response shape (`sessions.resolve` vs `sessions.get` vs `sessions.messages`) by grepping `/Users/prasiddhaparthsarthy/Desktop/openclaw/src/gateway/server-methods/sessions.*`. Plan step 1.
- Confirm `tools.list { agentId }` exists and returns the shape the allowlist multi-select expects, or pick the correct RPC. Plan step 1.

## Out of scope / future work

- Failure alert cooldown UX refinements (multiple escalations, alerting policies).
- Webhook delivery signing / retries configuration.
- Per-channel delivery templates.
- Global runs inbox as a sibling view.
- Cron scheduling helpers (natural language to cron expression, "next 30 days" visualization).
