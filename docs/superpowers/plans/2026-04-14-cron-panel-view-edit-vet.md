# Cron Panel: View, Edit, Vet — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the Crons control panel from a bare job list into a full view / edit / vet surface: prompts and delivery visible at a glance, a two-state UI that drills into any past run to show the full agent transcript, and an edit form that exposes every OpenClaw cron capability (model/fallbacks/tools, delivery to any channel, failure alerts, one-shot crons).

**Architecture:** Single panel file `CronPanel.tsx` becomes a state-machine container over an `overview` and `runs` state. Current ~700 LoC monolith is decomposed into a `cron/` subfolder (types, JobCard, JobList, JobEditDialog + sections, DeliveryPicker, ToolsAllowlist, SchedulePicker, RunList/Row/Filters, RunDetailPanel, RunTranscript, RunMetadata). All new data flows through existing WebSocket RPC passthrough — no backend changes. Transcript rendering reuses `MessageList` with a new `autoScroll={false}` prop and a session-message → `Message` adapter that mirrors `useAgentChat`'s existing loader.

**Tech Stack:** Next.js 16, React 19, TypeScript, SWR, Tailwind CSS v4, vitest + @testing-library/react, shadcn/ui primitives. WebSocket RPC via `useGatewayRpc` / `useGatewayRpcMutation`.

**Specification:** `docs/superpowers/specs/2026-04-14-cron-panel-view-edit-vet-design.md`

---

## File structure

New files (all under `apps/frontend/src/components/control/panels/cron/`):

- `types.ts` — frontend types matching OpenClaw's `CronJob` / `CronRunLogEntry`
- `formatters.ts` — `formatSchedule`, `formatDelivery`, `formatDuration`, `formatTokens`, `formatRelativeTime`, `formatAbsoluteTime`
- `JobCard.tsx` — State A card (prompt preview, delivery summary, running indicator, expandable runs)
- `JobList.tsx` — State A list + empty state + `+ New cron` button
- `JobEditDialog.tsx` — modal shell with footer
- `JobEditSections.tsx` — collapsible accordion sections wrapper
- `SchedulePicker.tsx` — at/every/cron picker with live preview
- `DeliveryPicker.tsx` — channel/account/to/threadId composite, uses `channels.status`
- `ToolsAllowlist.tsx` — multi-select backed by `tools.catalog`
- `FallbackModelList.tsx` — ordered multi-select of models
- `RunList.tsx` — State B left column, paginated
- `RunListRow.tsx` — individual run row
- `RunFilters.tsx` — status/date/query bar
- `RunDetailPanel.tsx` — State B right column container
- `RunTranscript.tsx` — read-only MessageList wrapper + session adapter
- `RunMetadata.tsx` — model/tokens/delivery/session id/next run block
- `sessionMessageAdapter.ts` — converts `sessions.get` / `chat.history` message payloads to `Message[]`

Modified:

- `CronPanel.tsx` — container + ViewState machine + SWR wiring (trimmed from ~700 LoC to orchestration only)
- `apps/frontend/src/components/chat/MessageList.tsx` — add `autoScroll?: boolean = true` prop

Tests (all under `apps/frontend/tests/unit/components/cron/`):

- `formatters.test.ts`
- `sessionMessageAdapter.test.ts`
- `JobCard.test.tsx`
- `JobList.test.tsx`
- `SchedulePicker.test.tsx`
- `DeliveryPicker.test.tsx`
- `ToolsAllowlist.test.tsx`
- `RunList.test.tsx`
- `RunDetailPanel.test.tsx`
- `RunTranscript.test.tsx`
- `CronPanel.test.tsx` (state machine transitions)

---

## Pre-flight

- [ ] **Step 0.1: Read the spec**

Read `docs/superpowers/specs/2026-04-14-cron-panel-view-edit-vet-design.md` end to end before starting. This plan executes that spec; deviate only if you hit a blocker and document it.

- [ ] **Step 0.2: Confirm transcript RPC in OpenClaw**

Run locally (not required to commit):

```bash
grep -n "['\"]chat.history['\"]\|['\"]sessions.get['\"]" /Users/prasiddhaparthsarthy/Desktop/openclaw/src/gateway/server-methods/*.ts
```

Expected: both handlers present. `sessions.get` lives in `sessions.ts:1443` accepting `{ key | sessionKey, limit? }` and returning `{ messages: unknown[] }`. `chat.history` lives in a chat-oriented handler and is already used by `apps/frontend/src/hooks/useAgentChat.ts:177` with `{ sessionKey, limit }` → `{ messages }`. Both return the same underlying session messages. **Use `chat.history`** — it's the established frontend pattern and the message-decoding logic in `useAgentChat.ts:193-204` can be lifted directly.

If that grep doesn't match, stop and investigate before proceeding.

---

## Task 1: Extract types to `cron/types.ts` (matching OpenClaw)

**Files:**
- Create: `apps/frontend/src/components/control/panels/cron/types.ts`
- Modify: `apps/frontend/src/components/control/panels/CronPanel.tsx:25-97` (remove local type defs and import from `./cron/types`)
- Test: `apps/frontend/tests/unit/components/cron/types.test.ts` (type-level assertions via `expectTypeOf`)

- [ ] **Step 1.1: Write `cron/types.ts`**

```ts
// apps/frontend/src/components/control/panels/cron/types.ts

export type CronScheduleKind = "at" | "every" | "cron";

export type CronSchedule =
  | { kind: "at"; at: string }
  | { kind: "every"; everyMs: number; anchorMs?: number }
  | { kind: "cron"; expr: string; tz?: string; staggerMs?: number };

export type CronSessionTarget = "main" | "isolated" | "current" | `session:${string}`;
export type CronWakeMode = "next-heartbeat" | "now";
export type CronDeliveryMode = "none" | "announce" | "webhook";
export type CronRunStatus = "ok" | "error" | "skipped";
export type CronDeliveryStatus = "delivered" | "not-delivered" | "unknown" | "not-requested";
export type CronFailoverReason =
  | "auth"
  | "format"
  | "rate_limit"
  | "billing"
  | "timeout"
  | "model_not_found"
  | "unknown";

export interface CronFailureDestination {
  channel?: string;
  to?: string;
  accountId?: string;
  mode?: "announce" | "webhook";
}

export interface CronDelivery {
  mode: CronDeliveryMode;
  channel?: string;
  to?: string;
  threadId?: string | number;
  accountId?: string;
  bestEffort?: boolean;
  failureDestination?: CronFailureDestination;
}

export interface CronFailureAlert {
  after?: number;
  channel?: string;
  to?: string;
  cooldownMs?: number;
  mode?: "announce" | "webhook";
  accountId?: string;
}

export interface CronAgentTurnPayload {
  kind: "agentTurn";
  message: string;
  model?: string;
  fallbacks?: string[];
  thinking?: string;
  timeoutSeconds?: number;
  lightContext?: boolean;
  toolsAllow?: string[];
  allowUnsafeExternalContent?: boolean;
}

export interface CronSystemEventPayload {
  kind: "systemEvent";
  text: string;
}

export type CronPayload = CronAgentTurnPayload | CronSystemEventPayload;

export interface CronJobState {
  nextRunAtMs?: number;
  runningAtMs?: number;
  lastRunAtMs?: number;
  lastRunStatus?: CronRunStatus;
  lastError?: string;
  lastErrorReason?: CronFailoverReason;
  lastDurationMs?: number;
  consecutiveErrors?: number;
  lastFailureAlertAtMs?: number;
  scheduleErrorCount?: number;
  lastDeliveryStatus?: CronDeliveryStatus;
  lastDeliveryError?: string;
  lastDelivered?: boolean;
}

export interface CronJob {
  id: string;
  agentId?: string;
  sessionKey?: string;
  name: string;
  description?: string;
  enabled: boolean;
  deleteAfterRun?: boolean;
  createdAtMs: number;
  updatedAtMs: number;
  schedule: CronSchedule;
  sessionTarget: CronSessionTarget;
  wakeMode: CronWakeMode;
  payload: CronPayload;
  delivery?: CronDelivery;
  failureAlert?: CronFailureAlert | false;
  state: CronJobState;
}

export interface CronUsageSummary {
  input_tokens?: number;
  output_tokens?: number;
  total_tokens?: number;
  cache_read_tokens?: number;
  cache_write_tokens?: number;
}

export interface CronRunEntry {
  jobId: string;
  jobName?: string;
  triggeredAtMs: number;
  completedAtMs?: number;
  status: CronRunStatus;
  error?: string;
  summary?: string;
  runAtMs?: number;
  durationMs?: number;
  nextRunAtMs?: number;
  delivered?: boolean;
  deliveryStatus?: CronDeliveryStatus;
  deliveryError?: string;
  sessionId?: string;
  sessionKey?: string;
  model?: string;
  provider?: string;
  usage?: CronUsageSummary;
}

export interface CronListResponse {
  jobs?: CronJob[];
  total?: number;
  hasMore?: boolean;
}

export interface CronRunsResponse {
  entries?: CronRunEntry[];
  total?: number;
  hasMore?: boolean;
}

export type CronJobPatch = Partial<
  Omit<CronJob, "id" | "createdAtMs" | "state" | "payload">
> & {
  payload?:
    | ({ kind: "agentTurn" } & Partial<Omit<CronAgentTurnPayload, "kind" | "toolsAllow">> & {
          toolsAllow?: string[] | null;
        })
    | ({ kind: "systemEvent" } & Partial<Omit<CronSystemEventPayload, "kind">>);
  delivery?: Partial<CronDelivery>;
  state?: Partial<CronJobState>;
};
```

Source of truth: `/Users/prasiddhaparthsarthy/Desktop/openclaw/src/cron/types.ts` and `types-shared.ts`.

- [ ] **Step 1.2: Write `types.test.ts`**

```ts
// apps/frontend/tests/unit/components/cron/types.test.ts
import { expectTypeOf, describe, it } from "vitest";
import type {
  CronJob,
  CronJobPatch,
  CronDelivery,
  CronAgentTurnPayload,
} from "@/components/control/panels/cron/types";

describe("cron types", () => {
  it("CronJob.payload narrows on kind", () => {
    const job = {} as CronJob;
    if (job.payload.kind === "agentTurn") {
      expectTypeOf(job.payload).toEqualTypeOf<CronAgentTurnPayload>();
    }
  });

  it("CronJobPatch.delivery allows partial and does not require mode", () => {
    expectTypeOf<CronJobPatch["delivery"]>().toEqualTypeOf<Partial<CronDelivery> | undefined>();
  });

  it("CronJob.failureAlert accepts false sentinel", () => {
    const job = {} as CronJob;
    expectTypeOf(job.failureAlert).extract<false>().toEqualTypeOf<false>();
  });
});
```

- [ ] **Step 1.3: Run the test — expect it to pass immediately**

```bash
cd apps/frontend && pnpm test -- tests/unit/components/cron/types.test.ts
```

Expected: PASS.

- [ ] **Step 1.4: Update `CronPanel.tsx` to import from `./cron/types`**

Remove lines 25–97 of `CronPanel.tsx` (the local type defs). Add at the top of the imports block:

```ts
import type {
  CronJob,
  CronListResponse,
  CronRunEntry,
  CronRunsResponse,
  CronSchedule,
  CronScheduleKind,
} from "./cron/types";
```

- [ ] **Step 1.5: Run typecheck + existing tests**

```bash
cd apps/frontend && pnpm run lint && pnpm test -- tests/unit/components/cron/
```

Expected: lint clean, types test passes. No behavior change yet, so no visual regression.

- [ ] **Step 1.6: Commit**

```bash
git add apps/frontend/src/components/control/panels/cron/types.ts \
        apps/frontend/tests/unit/components/cron/types.test.ts \
        apps/frontend/src/components/control/panels/CronPanel.tsx
git commit -m "refactor(cron): extract types matching OpenClaw cron model"
```

---

## Task 2: Add `autoScroll` prop to MessageList

We need a read-only transcript variant. The cheapest change is a prop on `MessageList` that disables the auto-scroll-to-bottom hook.

**Files:**
- Modify: `apps/frontend/src/components/chat/MessageList.tsx`
- Test: `apps/frontend/tests/unit/components/chat/MessageList.test.tsx` (extend)

- [ ] **Step 2.1: Add failing test for `autoScroll={false}`**

Open `apps/frontend/tests/unit/components/chat/MessageList.test.tsx` and add:

```tsx
import { vi } from "vitest";

const scrollToBottomSpy = vi.fn();
vi.mock("@/hooks/useScrollToBottom", () => ({
  useScrollToBottom: () => ({
    containerRef: { current: null },
    endRef: { current: null },
    scrollToBottom: scrollToBottomSpy,
    isAtBottom: true,
  }),
}));

describe("MessageList autoScroll", () => {
  it("does not auto-scroll when autoScroll={false}", () => {
    scrollToBottomSpy.mockClear();
    const msgs = [
      { id: "1", role: "user" as const, content: "hi" },
      { id: "2", role: "assistant" as const, content: "hello" },
    ];
    render(<MessageList messages={msgs} autoScroll={false} />);
    // The hook returns a noop scrollToBottom, but the component's internal
    // effect that calls it on new messages must not fire.
    expect(scrollToBottomSpy).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2.2: Run test — expect fail**

```bash
cd apps/frontend && pnpm test -- tests/unit/components/chat/MessageList.test.tsx
```

Expected: FAIL — `autoScroll` is not a known prop.

- [ ] **Step 2.3: Add `autoScroll` prop**

Edit `apps/frontend/src/components/chat/MessageList.tsx`:

```tsx
interface MessageListProps {
  messages: Message[];
  isTyping?: boolean;
  agentName?: string;
  onRetry?: (assistantMsgId: string) => void;
  onOpenFile?: (path: string) => void;
  autoScroll?: boolean;
}

export function MessageList({
  messages,
  isTyping,
  agentName,
  onRetry,
  onOpenFile,
  autoScroll = true,
}: MessageListProps) {
```

Find the `useEffect` inside `MessageList` that calls `scrollToBottom` on `[messages]` change (or wherever the scroll-on-new-message logic lives) and guard it:

```tsx
useEffect(() => {
  if (!autoScroll) return;
  scrollToBottom();
}, [messages, autoScroll, scrollToBottom]);
```

Keep the ref wiring (`containerRef`/`endRef`) unchanged so manual scrolling continues to work.

- [ ] **Step 2.4: Run test — expect pass**

```bash
cd apps/frontend && pnpm test -- tests/unit/components/chat/MessageList.test.tsx
```

Expected: PASS.

- [ ] **Step 2.5: Commit**

```bash
git add apps/frontend/src/components/chat/MessageList.tsx \
        apps/frontend/tests/unit/components/chat/MessageList.test.tsx
git commit -m "feat(chat): add autoScroll prop to MessageList for read-only contexts"
```

---

## Task 3: Write formatters

Pull schedule-formatting logic out of `CronPanel.tsx` and add new formatters for delivery, duration, tokens, relative time.

**Files:**
- Create: `apps/frontend/src/components/control/panels/cron/formatters.ts`
- Test: `apps/frontend/tests/unit/components/cron/formatters.test.ts`

- [ ] **Step 3.1: Write failing tests**

```ts
// apps/frontend/tests/unit/components/cron/formatters.test.ts
import { describe, it, expect } from "vitest";
import {
  formatSchedule,
  formatDelivery,
  formatDuration,
  formatTokens,
  formatRelativeTime,
} from "@/components/control/panels/cron/formatters";
import type { CronDelivery } from "@/components/control/panels/cron/types";

describe("formatSchedule", () => {
  it("formats cron expression with tz", () => {
    expect(formatSchedule({ kind: "cron", expr: "0 9 * * *", tz: "America/New_York" }))
      .toMatch(/9:00 AM|every day at 9/i);
  });
  it("formats every with unit rollup", () => {
    expect(formatSchedule({ kind: "every", everyMs: 60_000 })).toBe("every 1 minute");
    expect(formatSchedule({ kind: "every", everyMs: 60 * 60 * 1000 })).toBe("every 1 hour");
    expect(formatSchedule({ kind: "every", everyMs: 24 * 60 * 60 * 1000 })).toBe("every 1 day");
  });
  it("formats one-shot 'at'", () => {
    expect(formatSchedule({ kind: "at", at: "2026-04-15T09:00:00Z" })).toMatch(/2026/);
  });
});

describe("formatDelivery", () => {
  it("returns 'None' when mode=none or delivery is undefined", () => {
    expect(formatDelivery(undefined)).toBe("None");
    expect(formatDelivery({ mode: "none" })).toBe("None");
  });
  it("returns channel + target for announce with channel", () => {
    const d: CronDelivery = { mode: "announce", channel: "telegram", to: "@me" };
    expect(formatDelivery(d)).toBe("Telegram @me");
  });
  it("returns 'Chat' for announce without channel", () => {
    expect(formatDelivery({ mode: "announce" })).toBe("Chat");
  });
  it("returns 'Webhook: …' for webhook mode", () => {
    expect(formatDelivery({ mode: "webhook", to: "https://example.com/hook" }))
      .toMatch(/Webhook.*example\.com/);
  });
});

describe("formatDuration", () => {
  it("ms < 1s shows ms", () => { expect(formatDuration(450)).toBe("450ms"); });
  it("1s–60s shows seconds with 1 decimal", () => { expect(formatDuration(14_200)).toBe("14.2s"); });
  it(">= 60s shows m:ss", () => { expect(formatDuration(125_000)).toBe("2:05"); });
});

describe("formatTokens", () => {
  it("hides zeros", () => {
    expect(formatTokens({ input_tokens: 2341, output_tokens: 847, cache_read_tokens: 0 }))
      .toBe("2,341 in · 847 out");
  });
  it("shows cache hits when present", () => {
    expect(formatTokens({ input_tokens: 100, output_tokens: 50, cache_read_tokens: 1120 }))
      .toBe("100 in · 50 out · 1,120 cache-hit");
  });
});

describe("formatRelativeTime", () => {
  it("returns '2m ago' for 2 minutes past", () => {
    const now = Date.now();
    expect(formatRelativeTime(now - 120_000, now)).toBe("2m ago");
  });
  it("returns 'in 4h' for future", () => {
    const now = Date.now();
    expect(formatRelativeTime(now + 4 * 60 * 60 * 1000, now)).toBe("in 4h");
  });
});
```

- [ ] **Step 3.2: Run — expect fail**

```bash
cd apps/frontend && pnpm test -- tests/unit/components/cron/formatters.test.ts
```

Expected: FAIL — module not found.

- [ ] **Step 3.3: Implement formatters**

```ts
// apps/frontend/src/components/control/panels/cron/formatters.ts
import cronstrue from "cronstrue";
import type { CronDelivery, CronSchedule, CronUsageSummary } from "./types";

const CHANNEL_LABELS: Record<string, string> = {
  telegram: "Telegram",
  discord: "Discord",
  slack: "Slack",
  whatsapp: "WhatsApp",
  signal: "Signal",
};

export function formatSchedule(schedule: CronSchedule | undefined): string {
  if (!schedule) return "—";
  switch (schedule.kind) {
    case "at":
      return new Date(schedule.at).toLocaleString();
    case "every": {
      const ms = schedule.everyMs;
      const units: [number, string][] = [
        [24 * 60 * 60 * 1000, "day"],
        [60 * 60 * 1000, "hour"],
        [60 * 1000, "minute"],
        [1000, "second"],
      ];
      for (const [unitMs, label] of units) {
        if (ms % unitMs === 0 && ms >= unitMs) {
          const n = ms / unitMs;
          return `every ${n} ${label}${n === 1 ? "" : "s"}`;
        }
      }
      return `every ${ms}ms`;
    }
    case "cron": {
      try {
        const text = cronstrue.toString(schedule.expr, { throwExceptionOnParseError: true });
        return schedule.tz ? `${text} (${schedule.tz})` : text;
      } catch {
        return schedule.expr;
      }
    }
  }
}

export function formatDelivery(delivery: CronDelivery | undefined): string {
  if (!delivery || delivery.mode === "none") return "None";
  if (delivery.mode === "webhook") {
    try {
      const u = new URL(delivery.to ?? "");
      return `Webhook: ${u.host}`;
    } catch {
      return "Webhook";
    }
  }
  // announce
  if (!delivery.channel) return "Chat";
  const label = CHANNEL_LABELS[delivery.channel] ?? delivery.channel;
  return delivery.to ? `${label} ${delivery.to}` : label;
}

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const secs = Math.floor(ms / 1000);
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function formatTokens(usage: CronUsageSummary | undefined): string {
  if (!usage) return "—";
  const parts: string[] = [];
  if (usage.input_tokens) parts.push(`${usage.input_tokens.toLocaleString()} in`);
  if (usage.output_tokens) parts.push(`${usage.output_tokens.toLocaleString()} out`);
  if (usage.cache_read_tokens) parts.push(`${usage.cache_read_tokens.toLocaleString()} cache-hit`);
  if (usage.cache_write_tokens) parts.push(`${usage.cache_write_tokens.toLocaleString()} cache-write`);
  return parts.join(" · ") || "—";
}

export function formatRelativeTime(targetMs: number, nowMs: number = Date.now()): string {
  const diff = targetMs - nowMs;
  const abs = Math.abs(diff);
  const units: [number, string][] = [
    [24 * 60 * 60 * 1000, "d"],
    [60 * 60 * 1000, "h"],
    [60 * 1000, "m"],
    [1000, "s"],
  ];
  for (const [unit, label] of units) {
    if (abs >= unit) {
      const n = Math.floor(abs / unit);
      return diff < 0 ? `${n}${label} ago` : `in ${n}${label}`;
    }
  }
  return "just now";
}

export function formatAbsoluteTime(ms: number): string {
  return new Date(ms).toLocaleString();
}
```

- [ ] **Step 3.4: Run — expect pass**

```bash
cd apps/frontend && pnpm test -- tests/unit/components/cron/formatters.test.ts
```

Expected: PASS.

- [ ] **Step 3.5: Commit**

```bash
git add apps/frontend/src/components/control/panels/cron/formatters.ts \
        apps/frontend/tests/unit/components/cron/formatters.test.ts
git commit -m "feat(cron): add schedule/delivery/duration/token/time formatters"
```

---

## Task 4: Extract `JobCard` (refactor, no behavior change)

Lift the current job card rendering out of `CronPanel.tsx` into its own component. Ports existing behavior 1:1; enrichments come in Task 5.

**Files:**
- Create: `apps/frontend/src/components/control/panels/cron/JobCard.tsx`
- Modify: `apps/frontend/src/components/control/panels/CronPanel.tsx` (delete lifted code, import `JobCard`)
- Test: `apps/frontend/tests/unit/components/cron/JobCard.test.tsx`

- [ ] **Step 4.1: Write failing test for JobCard**

```tsx
// apps/frontend/tests/unit/components/cron/JobCard.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { JobCard } from "@/components/control/panels/cron/JobCard";
import type { CronJob } from "@/components/control/panels/cron/types";

const baseJob: CronJob = {
  id: "job-1",
  name: "Daily digest",
  enabled: true,
  createdAtMs: 1_700_000_000_000,
  updatedAtMs: 1_700_000_000_000,
  schedule: { kind: "cron", expr: "0 7 * * *", tz: "UTC" },
  sessionTarget: "isolated",
  wakeMode: "next-heartbeat",
  payload: { kind: "agentTurn", message: "Summarize today's news" },
  state: { nextRunAtMs: Date.now() + 3600_000, lastRunStatus: "ok", lastRunAtMs: Date.now() - 120_000 },
};

describe("JobCard (refactor)", () => {
  it("renders name, formatted schedule, and active badge", () => {
    render(
      <JobCard
        job={baseJob}
        expanded={false}
        onToggleExpand={vi.fn()}
        onEdit={vi.fn()}
        onPauseResume={vi.fn()}
        onRunNow={vi.fn()}
        onDelete={vi.fn()}
        onSelectRun={vi.fn()}
      />,
    );
    expect(screen.getByText("Daily digest")).toBeInTheDocument();
    expect(screen.getByText(/active/i)).toBeInTheDocument();
    expect(screen.getByText(/every day.*7/i)).toBeInTheDocument();
  });

  it("renders 'paused' badge when disabled", () => {
    render(
      <JobCard
        job={{ ...baseJob, enabled: false }}
        expanded={false}
        onToggleExpand={vi.fn()}
        onEdit={vi.fn()}
        onPauseResume={vi.fn()}
        onRunNow={vi.fn()}
        onDelete={vi.fn()}
        onSelectRun={vi.fn()}
      />,
    );
    expect(screen.getByText(/paused/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 4.2: Run — expect fail (module not found)**

```bash
cd apps/frontend && pnpm test -- tests/unit/components/cron/JobCard.test.tsx
```

- [ ] **Step 4.3: Create `JobCard.tsx`**

Move the relevant card JSX (the `map` over jobs in `CronPanel.tsx`, roughly lines 600–700) into a new `JobCard` component. The component's props are the interfaces used in the test above (`job`, `expanded`, `onToggleExpand`, `onEdit`, `onPauseResume`, `onRunNow`, `onDelete`, `onSelectRun`). Internally, it renders a single card exactly as today. Use `formatSchedule` from Task 3 instead of the local helper.

Key points:
- Receives one job and a set of callbacks — it does NOT call RPCs directly; the parent wires mutations.
- `onSelectRun(runEntry)` is a new callback. For this task, thread it through but the inline runs list still behaves as today (a list of rows, no click handler wired yet) — it's a no-op prop for now. Task 8 wires the click.
- Keep the inline-expand recent-runs list rendering untouched in this task.

- [ ] **Step 4.4: Replace the card loop in `CronPanel.tsx`**

Where the component maps jobs to inline card JSX, replace with `jobs.map(job => <JobCard key={job.id} job={job} ... />)`. Delete the now-unused formatSchedule local.

- [ ] **Step 4.5: Run JobCard test + broader app typecheck**

```bash
cd apps/frontend && pnpm test -- tests/unit/components/cron/JobCard.test.tsx && pnpm run lint
```

Expected: both pass. Visual manual check next.

- [ ] **Step 4.6: Manual smoke: run the frontend and confirm the crons panel still looks and behaves as it did before**

```bash
cd apps/frontend && pnpm run dev
```

Navigate to `/chat` → Control Panel → Crons. Confirm:
- Jobs list renders identical to before.
- Expand/collapse recent runs still works.
- Edit / Pause / Run now / Delete actions all still work.

Stop the dev server when done.

- [ ] **Step 4.7: Commit**

```bash
git add apps/frontend/src/components/control/panels/cron/JobCard.tsx \
        apps/frontend/tests/unit/components/cron/JobCard.test.tsx \
        apps/frontend/src/components/control/panels/CronPanel.tsx
git commit -m "refactor(cron): extract JobCard component; no behavior change"
```

---

## Task 5: Enrich `JobCard` — prompt preview, delivery summary, description, running indicator

Add the State A enrichments. This is the first user-visible change.

**Files:**
- Modify: `apps/frontend/src/components/control/panels/cron/JobCard.tsx`
- Modify: `apps/frontend/tests/unit/components/cron/JobCard.test.tsx`

- [ ] **Step 5.1: Extend JobCard test with failing enrichment cases**

```tsx
it("shows truncated prompt preview from payload.message", () => {
  const longPrompt = "Summarize today's top 3 TechCrunch posts and email me a brief summary with links and author names and ".repeat(3);
  render(<JobCard job={{ ...baseJob, payload: { kind: "agentTurn", message: longPrompt } }} {...noopProps} />);
  const el = screen.getByText(/Summarize today's top 3/);
  expect(el.textContent!.length).toBeLessThanOrEqual(203); // 200 chars + "..."
  expect(el.textContent).toMatch(/…$/);
});

it("shows delivery summary from delivery.channel+to", () => {
  render(<JobCard job={{ ...baseJob, delivery: { mode: "announce", channel: "telegram", to: "@me" } }} {...noopProps} />);
  expect(screen.getByText(/Delivers to:/)).toBeInTheDocument();
  expect(screen.getByText(/Telegram @me/)).toBeInTheDocument();
});

it("shows running indicator when state.runningAtMs is set", () => {
  render(<JobCard job={{ ...baseJob, state: { ...baseJob.state, runningAtMs: Date.now() - 1000 } }} {...noopProps} />);
  expect(screen.getByText(/Running now/i)).toBeInTheDocument();
});

it("shows description when set", () => {
  render(<JobCard job={{ ...baseJob, description: "Runs every morning at 7am" }} {...noopProps} />);
  expect(screen.getByText("Runs every morning at 7am")).toBeInTheDocument();
});

it("shows consecutive errors badge when >= 1 and enabled", () => {
  render(<JobCard job={{ ...baseJob, state: { ...baseJob.state, consecutiveErrors: 3, lastRunStatus: "error" } }} {...noopProps} />);
  expect(screen.getByText(/3 consecutive errors/i)).toBeInTheDocument();
});
```

(Define `noopProps` at the top of the file: `const noopProps = { expanded: false, onToggleExpand: vi.fn(), onEdit: vi.fn(), onPauseResume: vi.fn(), onRunNow: vi.fn(), onDelete: vi.fn(), onSelectRun: vi.fn() };`)

- [ ] **Step 5.2: Run — expect fails**

```bash
cd apps/frontend && pnpm test -- tests/unit/components/cron/JobCard.test.tsx
```

- [ ] **Step 5.3: Implement the enrichments in `JobCard.tsx`**

Inside the card layout (below the existing name/status header, above the expandable runs):

1. **Prompt preview**: for `payload.kind === "agentTurn"`, show a `<p>` with class `text-sm text-[#8a8578] line-clamp-2` containing `payload.message.slice(0, 200) + (payload.message.length > 200 ? "…" : "")`. Add `title={payload.message}` for full-text tooltip. For `systemEvent`, prefix with a small `<span className="text-xs uppercase tracking-wide text-[#8a8578] mr-2">system event</span>`.
2. **Delivery summary**: add a line `<span>Delivers to:</span> <span>{formatDelivery(job.delivery)}</span>` in the metadata row next to next-run and last-run.
3. **Description**: if `job.description`, render it as a muted line below the prompt preview.
4. **Running indicator**: if `state.runningAtMs` is set, add a subtle `ring-2 ring-[color]` pulse animation on the card root and a `<span className="inline-flex items-center gap-2"><span className="animate-pulse h-2 w-2 rounded-full bg-blue-500" />Running now…</span>` line in the metadata row (keep the next-run line present — they are independent).
5. **Consecutive errors badge**: if `job.enabled && (state.consecutiveErrors ?? 0) >= 1 && state.lastRunStatus === "error"`, add a small red badge reading `{n} consecutive errors`.

Import `formatDelivery` from `./formatters`.

- [ ] **Step 5.4: Run — expect pass**

```bash
cd apps/frontend && pnpm test -- tests/unit/components/cron/JobCard.test.tsx
```

- [ ] **Step 5.5: Manual smoke**

Run `pnpm run dev`, go to Crons panel, confirm:
- Prompt preview appears on each card.
- Delivery target shows (or "None" if not set).
- Cards with errors display the red consecutive-errors badge.

- [ ] **Step 5.6: Commit**

```bash
git add apps/frontend/src/components/control/panels/cron/JobCard.tsx \
        apps/frontend/tests/unit/components/cron/JobCard.test.tsx
git commit -m "feat(cron): surface prompt, delivery, description, and running state on job cards"
```

---

## Task 6: Extract `JobList` + add empty state

**Files:**
- Create: `apps/frontend/src/components/control/panels/cron/JobList.tsx`
- Modify: `apps/frontend/src/components/control/panels/CronPanel.tsx`
- Test: `apps/frontend/tests/unit/components/cron/JobList.test.tsx`

- [ ] **Step 6.1: Failing test**

```tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { JobList } from "@/components/control/panels/cron/JobList";

describe("JobList", () => {
  it("renders empty state when no jobs", () => {
    render(<JobList jobs={[]} onCreate={vi.fn()} {...cardHandlers} />);
    expect(screen.getByText(/no crons yet/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /create your first cron/i })).toBeInTheDocument();
  });
  it("renders N job cards when jobs exist", () => {
    const jobs = [ /* 3 CronJobs */ ];
    render(<JobList jobs={jobs} onCreate={vi.fn()} {...cardHandlers} />);
    expect(screen.getAllByRole("article")).toHaveLength(3); // JobCard uses <article>
  });
});
```

Add `role="article"` to the JobCard root in Task 4 if not already present.

- [ ] **Step 6.2: Implement `JobList.tsx`**

```tsx
"use client";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { JobCard } from "./JobCard";
import type { CronJob, CronRunEntry } from "./types";

interface JobListProps {
  jobs: CronJob[];
  expandedJobId: string | null;
  onToggleExpand: (jobId: string) => void;
  onCreate: () => void;
  onEdit: (job: CronJob) => void;
  onPauseResume: (job: CronJob) => void;
  onRunNow: (job: CronJob) => void;
  onDelete: (job: CronJob) => void;
  onSelectRun: (job: CronJob, run: CronRunEntry) => void;
}

export function JobList(props: JobListProps) {
  const { jobs, expandedJobId, onCreate } = props;

  if (jobs.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16">
        <p className="text-[#8a8578] mb-4">No crons yet</p>
        <Button onClick={onCreate}>
          <Plus className="h-4 w-4 mr-2" /> Create your first cron
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex justify-end">
        <Button size="sm" onClick={onCreate}>
          <Plus className="h-4 w-4 mr-2" /> New cron
        </Button>
      </div>
      {jobs.map((job) => (
        <JobCard
          key={job.id}
          job={job}
          expanded={expandedJobId === job.id}
          onToggleExpand={() => props.onToggleExpand(job.id)}
          onEdit={() => props.onEdit(job)}
          onPauseResume={() => props.onPauseResume(job)}
          onRunNow={() => props.onRunNow(job)}
          onDelete={() => props.onDelete(job)}
          onSelectRun={(run) => props.onSelectRun(job, run)}
        />
      ))}
    </div>
  );
}
```

- [ ] **Step 6.3: Wire `CronPanel.tsx` to render `JobList`**

Replace the existing jobs loop in `CronPanel.tsx` with `<JobList jobs={jobs} expandedJobId={expandedJobId} ... />`. Move the per-job handlers (mutations) up into `CronPanel`.

- [ ] **Step 6.4: Tests + smoke**

```bash
cd apps/frontend && pnpm test -- tests/unit/components/cron/JobList.test.tsx && pnpm run dev
```

Confirm the empty state appears when no crons exist, otherwise cards render as before.

- [ ] **Step 6.5: Commit**

```bash
git add apps/frontend/src/components/control/panels/cron/JobList.tsx \
        apps/frontend/tests/unit/components/cron/JobList.test.tsx \
        apps/frontend/src/components/control/panels/CronPanel.tsx
git commit -m "refactor(cron): extract JobList with empty state"
```

---

## Task 7: `ViewState` machine in `CronPanel`

Add the two-state transition primitive. Clicking a run in the inline recent-runs triggers State B; empty reducer wiring for now.

**Files:**
- Modify: `apps/frontend/src/components/control/panels/CronPanel.tsx`
- Modify: `apps/frontend/src/components/control/panels/cron/JobCard.tsx` (make inline run rows clickable)
- Test: `apps/frontend/tests/unit/components/cron/CronPanel.test.tsx`

- [ ] **Step 7.1: Test: clicking a run transitions to State B**

```tsx
// Mock useGatewayRpc to return 1 job with 1 run.
// Render CronPanel. Expand the job. Click a run row. Assert:
//  - Jobs list is no longer visible.
//  - "Back to jobs" button is visible.
//  - Job name appears in the State B header.
```

(See `AgentChannelsSection.test.tsx` for the SWR/mock pattern.)

- [ ] **Step 7.2: Implement `ViewState` in `CronPanel.tsx`**

```tsx
type ViewState =
  | { kind: "overview" }
  | { kind: "runs"; jobId: string; selectedRunTs: number | null };

const [view, setView] = useState<ViewState>({ kind: "overview" });
```

Render conditionally: `view.kind === "overview"` → `<JobList ... />`. `view.kind === "runs"` → placeholder `<div>Runs view for job {view.jobId}</div>` + `<Button onClick={() => setView({ kind: "overview" })}>← Back to jobs</Button>`.

Wire `onSelectRun` on `JobList` to `(job, run) => setView({ kind: "runs", jobId: job.id, selectedRunTs: run.triggeredAtMs })`.

In `JobCard.tsx`, make the inline run rows clickable (`onClick={() => props.onSelectRun(run)}` with `role="button"` and a hover style).

- [ ] **Step 7.3: Run + commit**

```bash
cd apps/frontend && pnpm test -- tests/unit/components/cron/CronPanel.test.tsx
git add apps/frontend/src/components/control/panels/cron/JobCard.tsx \
        apps/frontend/src/components/control/panels/CronPanel.tsx \
        apps/frontend/tests/unit/components/cron/CronPanel.test.tsx
git commit -m "feat(cron): add overview↔runs state machine with back navigation"
```

---

## Task 8: `RunList`, `RunListRow`, `RunFilters` (State B left column)

**Files:**
- Create: `apps/frontend/src/components/control/panels/cron/RunList.tsx`
- Create: `apps/frontend/src/components/control/panels/cron/RunListRow.tsx`
- Create: `apps/frontend/src/components/control/panels/cron/RunFilters.tsx`
- Modify: `apps/frontend/src/components/control/panels/CronPanel.tsx`
- Test: `apps/frontend/tests/unit/components/cron/RunList.test.tsx`

- [ ] **Step 8.1: Test: RunList renders rows and paginates**

```tsx
// Render RunList with 3 runs, one selected, onSelect mock.
// Assert 3 <button role="row"> elements, the selected one has aria-selected=true.
// Click an unselected row, assert onSelect called with the run.
```

- [ ] **Step 8.2: Implement `RunListRow`**

```tsx
// apps/frontend/src/components/control/panels/cron/RunListRow.tsx
import { CheckCircle2, XCircle, MinusCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatRelativeTime, formatDuration } from "./formatters";
import type { CronRunEntry } from "./types";

const ICONS = {
  ok: <CheckCircle2 className="h-4 w-4 text-green-600" />,
  error: <XCircle className="h-4 w-4 text-red-600" />,
  skipped: <MinusCircle className="h-4 w-4 text-yellow-600" />,
};

export function RunListRow({
  run,
  selected,
  onSelect,
}: {
  run: CronRunEntry;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      role="row"
      aria-selected={selected}
      onClick={onSelect}
      className={cn(
        "w-full flex items-center gap-3 px-3 py-2 text-left hover:bg-[#f3efe6]",
        selected && "bg-[#e8e3d9]",
      )}
    >
      {ICONS[run.status]}
      <span className="text-sm">{formatRelativeTime(run.triggeredAtMs)}</span>
      {run.durationMs !== undefined && (
        <span className="text-xs text-[#8a8578] ml-auto">{formatDuration(run.durationMs)}</span>
      )}
      {run.delivered === false && run.deliveryStatus === "not-delivered" && (
        <span className="text-xs text-red-600" title={run.deliveryError}>✗</span>
      )}
    </button>
  );
}
```

- [ ] **Step 8.3: Implement `RunFilters`**

```tsx
// Segmented status filter (All / OK / Error / Skipped) + free-text query input.
// Props: status, query, onStatusChange, onQueryChange.
```

- [ ] **Step 8.4: Implement `RunList`**

```tsx
"use client";
import { RunListRow } from "./RunListRow";
import { RunFilters } from "./RunFilters";
import type { CronRunEntry } from "./types";

interface RunListProps {
  runs: CronRunEntry[];
  selectedTs: number | null;
  onSelect: (run: CronRunEntry) => void;
  statusFilter: "all" | "ok" | "error" | "skipped";
  queryFilter: string;
  onStatusFilterChange: (s: "all" | "ok" | "error" | "skipped") => void;
  onQueryFilterChange: (q: string) => void;
  hasMore: boolean;
  onLoadMore: () => void;
  isLoading: boolean;
}

export function RunList(props: RunListProps) {
  return (
    <div className="flex flex-col h-full">
      <RunFilters
        status={props.statusFilter}
        query={props.queryFilter}
        onStatusChange={props.onStatusFilterChange}
        onQueryChange={props.onQueryFilterChange}
      />
      <div role="rowgroup" className="flex-1 overflow-y-auto">
        {props.runs.map((run) => (
          <RunListRow
            key={run.triggeredAtMs}
            run={run}
            selected={props.selectedTs === run.triggeredAtMs}
            onSelect={() => props.onSelect(run)}
          />
        ))}
        {props.hasMore && (
          <button
            onClick={props.onLoadMore}
            disabled={props.isLoading}
            className="w-full text-center py-3 text-sm text-[#8a8578] hover:text-[#1a1a1a]"
          >
            {props.isLoading ? "Loading…" : "Load more"}
          </button>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 8.5: Wire `CronPanel` to fetch runs in State B**

In `CronPanel.tsx`, add an SWR fetch keyed on `(view.jobId, statusFilter, queryFilter, limit)` that calls `cron.runs`:

```ts
const { data: runsData, mutate: mutateRuns } = useGatewayRpc<CronRunsResponse>(
  view.kind === "runs" ? "cron.runs" : null,
  view.kind === "runs" ? {
    scope: "job",
    id: view.jobId,
    limit,
    ...(statusFilter !== "all" ? { statuses: [statusFilter] } : {}),
    ...(queryFilter ? { query: queryFilter } : {}),
  } : null,
);
```

Render State B as a grid: `grid-cols-[320px_1fr]`. Left column is `<RunList />`. Right column is a placeholder `<div>Select a run to vet</div>` for now (filled in Task 10).

- [ ] **Step 8.6: Manual smoke**

Click a job's run in State A → transitions to State B → left column shows the job's runs with filters at top → selected run row is highlighted.

- [ ] **Step 8.7: Commit**

```bash
git add apps/frontend/src/components/control/panels/cron/RunList.tsx \
        apps/frontend/src/components/control/panels/cron/RunListRow.tsx \
        apps/frontend/src/components/control/panels/cron/RunFilters.tsx \
        apps/frontend/src/components/control/panels/CronPanel.tsx \
        apps/frontend/tests/unit/components/cron/RunList.test.tsx
git commit -m "feat(cron): state B left column — paginated runs list with filters"
```

---

## Task 9: Session-message adapter

Converts `sessions.get` / `chat.history` raw messages into `Message[]` the `MessageList` understands. Lifted from `useAgentChat.ts:193-204`.

**Files:**
- Create: `apps/frontend/src/components/control/panels/cron/sessionMessageAdapter.ts`
- Test: `apps/frontend/tests/unit/components/cron/sessionMessageAdapter.test.ts`

- [ ] **Step 9.1: Failing test**

```ts
import { describe, it, expect } from "vitest";
import { adaptSessionMessages } from "@/components/control/panels/cron/sessionMessageAdapter";

describe("adaptSessionMessages", () => {
  it("maps user and assistant turns with text content", () => {
    const raw = [
      { role: "user", content: [{ type: "text", text: "hi" }] },
      { role: "assistant", content: [{ type: "text", text: "hello" }] },
    ];
    const msgs = adaptSessionMessages(raw);
    expect(msgs).toEqual([
      { id: "history-0", role: "user", content: "hi" },
      { id: "history-1", role: "assistant", content: "hello" },
    ]);
  });

  it("extracts thinking blocks into `thinking` field", () => {
    const raw = [
      { role: "assistant", content: [
        { type: "thinking", text: "considering options" },
        { type: "text", text: "here you go" },
      ]},
    ];
    expect(adaptSessionMessages(raw)).toEqual([
      { id: "history-0", role: "assistant", content: "here you go", thinking: "considering options" },
    ]);
  });

  it("filters out system/tool messages and empty content", () => {
    const raw = [
      { role: "system", content: [{ type: "text", text: "boot" }] },
      { role: "tool", content: [] },
      { role: "user", content: [] },
      { role: "assistant", content: [{ type: "text", text: "done" }] },
    ];
    expect(adaptSessionMessages(raw)).toEqual([
      { id: "history-0", role: "assistant", content: "done" },
    ]);
  });
});
```

- [ ] **Step 9.2: Implement the adapter**

```ts
// apps/frontend/src/components/control/panels/cron/sessionMessageAdapter.ts

export interface AdaptedMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  thinking?: string;
}

interface RawContentBlock {
  type: string;
  text?: string;
}

interface RawMessage {
  role: string;
  content?: RawContentBlock[];
}

function extractText(content: RawContentBlock[] | undefined): string {
  if (!content) return "";
  return content
    .filter((b) => b.type === "text" && typeof b.text === "string")
    .map((b) => b.text)
    .join("");
}

function extractThinking(content: RawContentBlock[] | undefined): string | undefined {
  if (!content) return undefined;
  const thinking = content
    .filter((b) => b.type === "thinking" && typeof b.text === "string")
    .map((b) => b.text)
    .join("");
  return thinking || undefined;
}

export function adaptSessionMessages(raw: unknown[] | undefined): AdaptedMessage[] {
  if (!raw) return [];
  const out: AdaptedMessage[] = [];
  for (let i = 0; i < raw.length; i++) {
    const m = raw[i] as RawMessage;
    if (m.role !== "user" && m.role !== "assistant") continue;
    const content = extractText(m.content);
    const thinking = extractThinking(m.content);
    if (!content && !thinking) continue;
    out.push({
      id: `history-${i}`,
      role: m.role,
      content,
      ...(thinking ? { thinking } : {}),
    });
  }
  return out;
}
```

- [ ] **Step 9.3: Run + commit**

```bash
cd apps/frontend && pnpm test -- tests/unit/components/cron/sessionMessageAdapter.test.ts
git add apps/frontend/src/components/control/panels/cron/sessionMessageAdapter.ts \
        apps/frontend/tests/unit/components/cron/sessionMessageAdapter.test.ts
git commit -m "feat(cron): add session-message-to-Message adapter"
```

---

## Task 10: `RunTranscript` + `RunMetadata` + `RunDetailPanel`

Assemble the right-column run detail.

**Files:**
- Create: `apps/frontend/src/components/control/panels/cron/RunTranscript.tsx`
- Create: `apps/frontend/src/components/control/panels/cron/RunMetadata.tsx`
- Create: `apps/frontend/src/components/control/panels/cron/RunDetailPanel.tsx`
- Modify: `apps/frontend/src/components/control/panels/CronPanel.tsx`
- Test: `apps/frontend/tests/unit/components/cron/RunDetailPanel.test.tsx`
- Test: `apps/frontend/tests/unit/components/cron/RunTranscript.test.tsx`

- [ ] **Step 10.1: Test `RunTranscript`**

```tsx
// Mock useGatewayRpc. When sessionKey provided → returns { messages: [...] }.
// Assert rendered MessageList contains transcript text.
// When sessionKey missing → renders "No transcript available".
// When RPC errors → renders banner with retry.
```

- [ ] **Step 10.2: Implement `RunTranscript`**

```tsx
"use client";
import { useGatewayRpc } from "@/hooks/useGatewayRpc";
import { MessageList } from "@/components/chat/MessageList";
import { adaptSessionMessages } from "./sessionMessageAdapter";

interface ChatHistoryResp { messages?: unknown[] }

export function RunTranscript({ sessionKey }: { sessionKey: string | undefined }) {
  if (!sessionKey) {
    return <div className="p-6 text-sm text-[#8a8578]">No transcript available for this run.</div>;
  }
  const { data, error, isLoading, mutate } = useGatewayRpc<ChatHistoryResp>(
    "chat.history",
    { sessionKey, limit: 200 },
  );
  if (isLoading) {
    return <div className="p-6 text-sm text-[#8a8578]">Loading transcript…</div>;
  }
  if (error) {
    return (
      <div className="p-6 text-sm text-red-700">
        Transcript unavailable: {String(error?.message ?? error)}.
        <button onClick={() => mutate()} className="ml-2 underline">Retry</button>
      </div>
    );
  }
  const messages = adaptSessionMessages(data?.messages);
  if (messages.length === 0) {
    return <div className="p-6 text-sm text-[#8a8578]">No transcript available for this run.</div>;
  }
  return <MessageList messages={messages} autoScroll={false} />;
}

export function firstUserMessage(messages: ReturnType<typeof adaptSessionMessages>): string | undefined {
  return messages.find((m) => m.role === "user")?.content;
}
```

- [ ] **Step 10.3: Implement `RunMetadata`**

```tsx
import { formatTokens, formatRelativeTime } from "./formatters";
import type { CronRunEntry } from "./types";

const DELIVERY_STATUS_LABEL: Record<string, string> = {
  delivered: "✓ Delivered",
  "not-delivered": "✗ Delivery failed",
  unknown: "Delivery unknown",
  "not-requested": "No delivery configured",
};

export function RunMetadata({
  run,
  nextRunAtMs,
}: { run: CronRunEntry; nextRunAtMs: number | undefined }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 px-6 py-4 text-sm border-t border-[#e0dbd0]">
      {run.model && (<><dt className="text-[#8a8578]">Model</dt><dd>{run.model}{run.provider ? ` · ${run.provider}` : ""}</dd></>)}
      {run.usage && (<><dt className="text-[#8a8578]">Tokens</dt><dd>{formatTokens(run.usage)}</dd></>)}
      {run.deliveryStatus && (
        <>
          <dt className="text-[#8a8578]">Delivery</dt>
          <dd>
            {DELIVERY_STATUS_LABEL[run.deliveryStatus] ?? run.deliveryStatus}
            {run.deliveryError && <div className="text-xs text-red-600">{run.deliveryError}</div>}
          </dd>
        </>
      )}
      {run.sessionId && (<><dt className="text-[#8a8578]">Session</dt><dd className="font-mono text-xs">{run.sessionId.slice(0, 8)}…</dd></>)}
      {nextRunAtMs && (<><dt className="text-[#8a8578]">Next run</dt><dd>{formatRelativeTime(nextRunAtMs)}</dd></>)}
    </dl>
  );
}
```

- [ ] **Step 10.4: Implement `RunDetailPanel`**

```tsx
"use client";
import { useState } from "react";
import { X, ChevronDown, ChevronRight, Play, Pencil, Copy } from "lucide-react";
import { Button } from "@/components/ui/button";
import { RunTranscript, firstUserMessage } from "./RunTranscript";
import { RunMetadata } from "./RunMetadata";
import { adaptSessionMessages } from "./sessionMessageAdapter";
import { formatAbsoluteTime, formatDuration } from "./formatters";
import { useGatewayRpc } from "@/hooks/useGatewayRpc";
import type { CronJob, CronRunEntry } from "./types";

const STATUS_PILL: Record<string, string> = {
  ok: "bg-green-100 text-green-800",
  error: "bg-red-100 text-red-800",
  skipped: "bg-yellow-100 text-yellow-800",
};

export function RunDetailPanel({
  run,
  job,
  onClose,
  onRunNow,
  onEdit,
}: {
  run: CronRunEntry;
  job: CronJob;
  onClose: () => void;
  onRunNow: () => void;
  onEdit: () => void;
}) {
  const [promptOpen, setPromptOpen] = useState(false);

  const { data: transcriptData } = useGatewayRpc<{ messages?: unknown[] }>(
    run.sessionKey ? "chat.history" : null,
    run.sessionKey ? { sessionKey: run.sessionKey, limit: 200 } : null,
  );
  const adaptedMessages = adaptSessionMessages(transcriptData?.messages);
  const firstUserMsg = firstUserMessage(adaptedMessages);
  const displayedPrompt =
    firstUserMsg ??
    (job.payload.kind === "agentTurn" ? job.payload.message : job.payload.text);

  const promptEditedSinceRun =
    job.updatedAtMs > run.triggeredAtMs && firstUserMsg === undefined;

  const copyPrompt = () => { navigator.clipboard.writeText(displayedPrompt ?? "").catch(() => {}); };

  return (
    <div className="flex flex-col h-full bg-[#faf7f2] border-l border-[#e0dbd0]">
      <div className="flex items-center gap-3 px-4 h-14 border-b border-[#e0dbd0]">
        <span className={`px-2 py-0.5 rounded text-xs uppercase ${STATUS_PILL[run.status]}`}>
          {run.status}
        </span>
        <span className="text-sm">{formatAbsoluteTime(run.triggeredAtMs)}</span>
        {run.durationMs !== undefined && (
          <span className="text-xs text-[#8a8578]">· {formatDuration(run.durationMs)}</span>
        )}
        <div className="flex-1" />
        <Button size="sm" variant="outline" onClick={onRunNow}><Play className="h-3 w-3 mr-1" /> Run now</Button>
        <Button size="sm" variant="outline" onClick={onEdit}><Pencil className="h-3 w-3 mr-1" /> Edit job</Button>
        <Button size="sm" variant="outline" onClick={copyPrompt}><Copy className="h-3 w-3 mr-1" /> Copy prompt</Button>
        <button onClick={onClose} className="text-[#8a8578] hover:text-[#1a1a1a]"><X className="h-4 w-4" /></button>
      </div>

      {run.status === "error" && run.error && (
        <div className="mx-4 my-3 p-3 rounded bg-red-50 border border-red-200 text-sm">
          <div className="text-red-800 font-medium">Run failed</div>
          <div className="text-red-700 mt-1">{run.error}</div>
        </div>
      )}

      <div className="px-4 py-3 border-b border-[#e0dbd0]">
        <button
          onClick={() => setPromptOpen((v) => !v)}
          className="flex items-center gap-1 text-sm text-[#1a1a1a]"
          aria-expanded={promptOpen}
        >
          {promptOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          Prompt
          {promptEditedSinceRun && (
            <span className="ml-2 text-xs text-[#8a8578]">(job edited since this run)</span>
          )}
        </button>
        {promptOpen && (
          <pre className="mt-2 text-sm whitespace-pre-wrap font-mono text-[#1a1a1a] bg-[#f3efe6] p-3 rounded">
            {displayedPrompt ?? "—"}
          </pre>
        )}
      </div>

      <div className="flex-1 overflow-y-auto">
        <RunTranscript sessionKey={run.sessionKey} />
      </div>

      <RunMetadata run={run} nextRunAtMs={job.state.nextRunAtMs} />
    </div>
  );
}
```

- [ ] **Step 10.5: Wire into `CronPanel.tsx`**

In the runs view render, replace the placeholder right column with:

```tsx
{selectedRun ? (
  <RunDetailPanel
    run={selectedRun}
    job={selectedJob}
    onClose={() => setView({ kind: "runs", jobId: view.jobId, selectedRunTs: null })}
    onRunNow={() => handleRunNow(selectedJob)}
    onEdit={() => handleEdit(selectedJob)}
  />
) : (
  <div className="flex items-center justify-center h-full text-[#8a8578]">Select a run to vet</div>
)}
```

Where `selectedRun = runs.find(r => r.triggeredAtMs === view.selectedRunTs)`.

- [ ] **Step 10.6: Test end-to-end + smoke**

```bash
cd apps/frontend && pnpm test -- tests/unit/components/cron/RunDetailPanel.test.tsx tests/unit/components/cron/RunTranscript.test.tsx
```

Then manual: trigger a cron run in dev, click it, confirm transcript + metadata + prompt all render.

- [ ] **Step 10.7: Commit**

```bash
git add apps/frontend/src/components/control/panels/cron/RunTranscript.tsx \
        apps/frontend/src/components/control/panels/cron/RunMetadata.tsx \
        apps/frontend/src/components/control/panels/cron/RunDetailPanel.tsx \
        apps/frontend/src/components/control/panels/CronPanel.tsx \
        apps/frontend/tests/unit/components/cron/RunDetailPanel.test.tsx \
        apps/frontend/tests/unit/components/cron/RunTranscript.test.tsx
git commit -m "feat(cron): state B run detail panel — transcript, prompt, metadata"
```

---

## Task 11: Extract `JobEditDialog` + `JobEditSections` (refactor, no new fields)

Lift the current edit form out of `CronPanel.tsx` into its own components. Sections become collapsible accordions. No new fields yet; field set stays identical to today's (name, schedule kind/expr, message, enabled).

**Files:**
- Create: `apps/frontend/src/components/control/panels/cron/JobEditDialog.tsx`
- Create: `apps/frontend/src/components/control/panels/cron/JobEditSections.tsx`
- Modify: `apps/frontend/src/components/control/panels/CronPanel.tsx`
- Test: `apps/frontend/tests/unit/components/cron/JobEditDialog.test.tsx`

- [ ] **Step 11.1: Write tests for the dialog shape**

```tsx
// Test: renders "Basics" and "Delivery" sections open, others closed.
// Test: Save button calls onSave with the form state.
// Test: Cancel button calls onCancel.
```

- [ ] **Step 11.2: Implement the dialog + sections shell**

`JobEditSections` is a map: `{ id, title, defaultOpen, children }[]` rendered as accordions with a simple chevron + click-to-toggle header. No animation required.

Keep existing form state (`FormState`) inside `JobEditDialog` unchanged for now.

- [ ] **Step 11.3: Commit**

```bash
git add apps/frontend/src/components/control/panels/cron/JobEditDialog.tsx \
        apps/frontend/src/components/control/panels/cron/JobEditSections.tsx \
        apps/frontend/src/components/control/panels/CronPanel.tsx \
        apps/frontend/tests/unit/components/cron/JobEditDialog.test.tsx
git commit -m "refactor(cron): extract JobEditDialog with accordion sections"
```

---

## Task 12: `SchedulePicker` with live preview

**Files:**
- Create: `apps/frontend/src/components/control/panels/cron/SchedulePicker.tsx`
- Modify: `apps/frontend/src/components/control/panels/cron/JobEditDialog.tsx`
- Test: `apps/frontend/tests/unit/components/cron/SchedulePicker.test.tsx`

- [ ] **Step 12.1: Write failing tests**

```tsx
// Test: "cron" kind shows expression input + timezone dropdown + next-3-fires preview.
// Test: "every" kind shows number input + unit dropdown.
// Test: "at" kind shows datetime-local input.
// Test: next-3-fires preview shows 3 parsed dates for valid cron expr.
// Test: invalid cron expr shows "Parse error" and marks preview invalid.
```

- [ ] **Step 12.2: Implement `SchedulePicker`**

Props: `schedule: CronSchedule | undefined`, `onChange: (s: CronSchedule) => void`, `isValid: boolean`. Use `cronstrue` (already imported in current `CronPanel.tsx`) for human-readable text. Use `cron-parser` (add to package.json if not present; check first) for computing next fires:

```bash
cd apps/frontend && pnpm ls cron-parser 2>/dev/null
```

If absent: `pnpm add cron-parser`. Commit the `package.json` / lockfile change in this task.

Preview renders up to 3 upcoming fire times from `CronExpressionParser.parse(expr, { tz })`.

- [ ] **Step 12.3: Wire into `JobEditDialog`**

Replace the existing inline schedule inputs with `<SchedulePicker schedule={...} onChange={...} />`. Form state derives `schedule` on save as today.

- [ ] **Step 12.4: Test + commit**

```bash
cd apps/frontend && pnpm test -- tests/unit/components/cron/SchedulePicker.test.tsx
git add apps/frontend/src/components/control/panels/cron/SchedulePicker.tsx \
        apps/frontend/src/components/control/panels/cron/JobEditDialog.tsx \
        apps/frontend/tests/unit/components/cron/SchedulePicker.test.tsx \
        apps/frontend/package.json apps/frontend/pnpm-lock.yaml
git commit -m "feat(cron): SchedulePicker with live next-fires preview"
```

---

## Task 13: `DeliveryPicker`

**Files:**
- Create: `apps/frontend/src/components/control/panels/cron/DeliveryPicker.tsx`
- Modify: `apps/frontend/src/components/control/panels/cron/JobEditDialog.tsx`
- Test: `apps/frontend/tests/unit/components/cron/DeliveryPicker.test.tsx`

- [ ] **Step 13.1: Failing tests**

```tsx
// Mock channels.status → { telegram: [{ account_id: "a1", linked: true }], discord: [], slack: [] }.
// Test: mode=None hides channel/account/to fields.
// Test: mode=Announce shows channel dropdown with "Chat" + "Telegram" (discord/slack omitted — not enabled).
// Test: selecting Telegram shows accountId (only one account, hidden) + to + threadId.
// Test: mode=Webhook shows URL input only; invalid URL shows error.
// Test: failure-destination sub-section toggles open; when open, same picker rendered with different onChange.
```

- [ ] **Step 13.2: Implement `DeliveryPicker`**

Props:

```tsx
interface DeliveryPickerProps {
  value: CronDelivery | undefined;
  onChange: (d: CronDelivery | undefined) => void;
  label?: string; // defaults "Delivery"; used "Where to send failure notifications (if different)" for nested
}
```

Internal fetch of `channels.status` via `useGatewayRpc`. Filter channels where the account list is non-empty (means user has at least one linked account for that channel). Always include a synthetic `{ id: "__chat__", label: "Chat" }` entry that maps to `channel: undefined` in the value.

Per-channel metadata for help text + thread support (hard-coded map):

```ts
const CHANNEL_META: Record<string, { helpTo: string; hasThreads: boolean }> = {
  telegram: { helpTo: "@handle or chat ID", hasThreads: true },
  discord:  { helpTo: "#channel or user", hasThreads: true },
  slack:    { helpTo: "@user or #channel", hasThreads: true },
  whatsapp: { helpTo: "+1234567890", hasThreads: false },
  signal:   { helpTo: "+1234567890", hasThreads: false },
};
```

Webhook URL validation: try `new URL(value)`, mark error if throws.

Failure-destination nested picker: same component, passed with pre-set label and a different `onChange` that writes to `value.failureDestination`.

- [ ] **Step 13.3: Wire into `JobEditDialog`**

Add a new "Delivery" accordion section (open by default) with the picker. Persist `delivery` on the form state; include it in the `cron.add`/`cron.update` payloads.

For create, default to `{ mode: "announce" }` (Chat) — see Task 16.

- [ ] **Step 13.4: Test + smoke**

```bash
cd apps/frontend && pnpm test -- tests/unit/components/cron/DeliveryPicker.test.tsx
```

Manual: open edit dialog, change delivery to Telegram with a chat ID, save, refresh, confirm the card shows `Delivers to: Telegram …`.

- [ ] **Step 13.5: Commit**

```bash
git add apps/frontend/src/components/control/panels/cron/DeliveryPicker.tsx \
        apps/frontend/src/components/control/panels/cron/JobEditDialog.tsx \
        apps/frontend/tests/unit/components/cron/DeliveryPicker.test.tsx
git commit -m "feat(cron): DeliveryPicker (modes, channels, accounts, failure destination)"
```

---

## Task 14: Agent execution section (model, fallbacks, timeout, thinking, lightContext)

**Files:**
- Create: `apps/frontend/src/components/control/panels/cron/FallbackModelList.tsx`
- Modify: `apps/frontend/src/components/control/panels/cron/JobEditDialog.tsx`
- Test: `apps/frontend/tests/unit/components/cron/FallbackModelList.test.tsx`

- [ ] **Step 14.1: Implement `FallbackModelList`**

Ordered list with per-row model picker (reuse the existing `ModelSelector` from `@/components/chat/ModelSelector`), up/down reorder buttons, remove button, and an "Add fallback" button.

- [ ] **Step 14.2: Add "Agent execution" section to `JobEditDialog`**

Closed by default. Fields:

- `payload.model` — `<ModelSelector value={model} onChange={setModel} allowNull />` with null = "Use agent default".
- `payload.fallbacks` — `<FallbackModelList value={fallbacks} onChange={setFallbacks} />`.
- `payload.timeoutSeconds` — number input, placeholder "default".
- `payload.thinking` — text input with help tooltip.
- `payload.lightContext` — `<Checkbox />`.

Include these in the save payload.

- [ ] **Step 14.3: Tests + commit**

```bash
cd apps/frontend && pnpm test -- tests/unit/components/cron/FallbackModelList.test.tsx tests/unit/components/cron/JobEditDialog.test.tsx
git add apps/frontend/src/components/control/panels/cron/FallbackModelList.tsx \
        apps/frontend/src/components/control/panels/cron/JobEditDialog.tsx \
        apps/frontend/tests/unit/components/cron/FallbackModelList.test.tsx
git commit -m "feat(cron): Agent execution section (model, fallbacks, timeout, thinking, lightContext)"
```

---

## Task 15: `ToolsAllowlist`

**Files:**
- Create: `apps/frontend/src/components/control/panels/cron/ToolsAllowlist.tsx`
- Modify: `apps/frontend/src/components/control/panels/cron/JobEditDialog.tsx`
- Test: `apps/frontend/tests/unit/components/cron/ToolsAllowlist.test.tsx`

- [ ] **Step 15.1: Failing tests**

```tsx
// Mock tools.catalog → { groups: [{ id: "core", tools: [{ id: "bash" }, { id: "web_search" }] }] }.
// Test: dropdown lists available tools grouped by group id.
// Test: selecting tools adds them as chips; clicking chip × removes them.
// Test: empty selection shows help "Empty = all tools allowed".
// Test: onChange fires with string[].
```

- [ ] **Step 15.2: Implement**

Fetches `tools.catalog` via `useGatewayRpc<{ groups: { id: string; tools: { id: string }[] }[] }>` with `{ agentId, includePlugins: true }`. Shows a multi-select with chips. Renders help text when empty.

- [ ] **Step 15.3: Wire into Agent execution section of `JobEditDialog`**

Below the thinking field, add `<ToolsAllowlist agentId={form.agentId} value={form.toolsAllow} onChange={setToolsAllow} />`.

- [ ] **Step 15.4: Commit**

```bash
git add apps/frontend/src/components/control/panels/cron/ToolsAllowlist.tsx \
        apps/frontend/src/components/control/panels/cron/JobEditDialog.tsx \
        apps/frontend/tests/unit/components/cron/ToolsAllowlist.test.tsx
git commit -m "feat(cron): ToolsAllowlist backed by tools.catalog"
```

---

## Task 16: Failure alerts + Advanced sections + create-defaults

**Files:**
- Modify: `apps/frontend/src/components/control/panels/cron/JobEditDialog.tsx`

- [ ] **Step 16.1: Add "Failure alerts" section**

Enabled-checkbox gates the rest. When on:
- `after` — number, default 3.
- nested `DeliveryPicker` for destination (re-uses channel/account/to/mode).
- `cooldownMs` — number + unit picker (minutes/hours), default 60 min → 3_600_000.

On save: `failureAlert: enabled ? { after, channel, to, accountId, mode, cooldownMs } : false`.

- [ ] **Step 16.2: Add "Advanced" section**

- `deleteAfterRun` — `<Checkbox />` with warning text. Confirm dialog when toggled ON.
- `wakeMode` — segmented `next-heartbeat` | `now`.
- `agentId` — reuse existing agent picker (e.g. `useAgents` hook).

- [ ] **Step 16.3: Create-form defaults**

Extend the form's initial state for `mode: "create"`:

```ts
const CREATE_DEFAULTS = (channels: ChannelsStatus): Partial<FormState> => ({
  enabled: true,
  scheduleKind: "every",
  everyValue: 1,
  everyUnit: "days",
  delivery: { mode: "announce", channel: pickFirstEnabledChannel(channels) ?? undefined },
  wakeMode: "next-heartbeat",
});
```

Where `pickFirstEnabledChannel` prefers `undefined` (chat) if no channels are linked, else the first linked channel id.

- [ ] **Step 16.4: Test + smoke**

Open the "New cron" dialog, confirm defaults populate. Create a cron with failure alerts + custom fallbacks. Confirm it saves and reloads correctly.

- [ ] **Step 16.5: Commit**

```bash
git add apps/frontend/src/components/control/panels/cron/JobEditDialog.tsx \
        apps/frontend/tests/unit/components/cron/JobEditDialog.test.tsx
git commit -m "feat(cron): Failure alerts, Advanced sections, and create-form defaults"
```

---

## Task 17: Auto-refresh + edge cases

**Files:**
- Modify: `apps/frontend/src/components/control/panels/CronPanel.tsx`
- Modify: `apps/frontend/src/components/control/panels/cron/RunDetailPanel.tsx`
- Test: `apps/frontend/tests/unit/components/cron/CronPanel.test.tsx`

- [ ] **Step 17.1: SWR config**

Add `refreshInterval: 30_000, revalidateOnFocus: true` to the `cron.list` hook options. Ensure the interval only runs while the panel is mounted (SWR handles this automatically). Add the same for `cron.runs` when in State B.

- [ ] **Step 17.2: Optimistic toggle**

Wrap the enabled/disabled toggle mutation with optimistic state: flip the card badge immediately, roll back on error.

- [ ] **Step 17.3: Deleted-job handling in State B**

If `job` is not found in `jobs` array while in State B (`view.kind === "runs" && !selectedJob`), show a `(deleted)` badge in the top header and disable `Run now` / `Edit job` actions in `RunDetailPanel`.

- [ ] **Step 17.4: No-agents empty state**

If `agents.list` returns empty, disable `+ New cron` and show helper text "Create an agent first" above the job list.

- [ ] **Step 17.5: Error banners**

- `cron.list` fails: red banner at top of State A with retry button.
- `cron.runs` fails: same pattern, in State B left column.

- [ ] **Step 17.6: Test + commit**

```bash
cd apps/frontend && pnpm test -- tests/unit/components/cron/CronPanel.test.tsx
git add apps/frontend/src/components/control/panels/cron/RunDetailPanel.tsx \
        apps/frontend/src/components/control/panels/CronPanel.tsx \
        apps/frontend/tests/unit/components/cron/CronPanel.test.tsx
git commit -m "feat(cron): auto-refresh, optimistic toggle, deleted-job handling, error banners"
```

---

## Task 18: Full-suite verification + final smoke

- [ ] **Step 18.1: Run all cron tests**

```bash
cd apps/frontend && pnpm test -- tests/unit/components/cron/ tests/unit/components/chat/MessageList.test.tsx
```

Expected: all green.

- [ ] **Step 18.2: Lint + typecheck**

```bash
cd apps/frontend && pnpm run lint
```

Expected: clean.

- [ ] **Step 18.3: Full frontend unit suite**

```bash
cd apps/frontend && pnpm test
```

Expected: no regressions in unrelated test files.

- [ ] **Step 18.4: E2E smoke against dev**

```bash
cd apps/frontend && pnpm run dev
```

In browser (logged into a dev test account), walk through:

1. Open Control Panel → Crons.
2. Confirm existing cron cards show prompt preview, delivery summary, and last-run badge.
3. Click `+ New cron`, create a cron with: a schedule, a prompt, Telegram delivery to a handle, model override, tool allowlist of 2 tools, failure alert after 2 consecutive failures with 30 min cooldown. Save.
4. Confirm the new card renders with the delivery summary you set.
5. Click `Run now` on the new cron → wait for run to finish.
6. Expand the card → click the recent run → State B loads.
7. Left column shows the runs list, filter by "ok", confirm the filter narrows the list.
8. Click the run → right panel loads the transcript (via `chat.history`), prompt block is collapsible and contains the first user message, metadata shows model/tokens/delivery/session id.
9. Click `Edit job` in the run detail → edit form opens with all fields populated from the job.
10. Click `Back to jobs` → State A returns, exit without unmounting.
11. Delete the test cron.

- [ ] **Step 18.5: Final commit if any fixes surfaced**

Commit any residual fixes with a clear message. If nothing needed, skip.

---

## Self-review (performed while writing this plan)

### Spec coverage

| Spec section | Task(s) |
|---|---|
| Two-state UI (State A / State B) | 7 (state machine), 8 (runs list), 10 (run detail) |
| State A card: prompt preview, delivery, description, running indicator, consecutive-errors badge | 5 |
| Clickable run rows transitioning to State B | 7 |
| State B left column: scoped runs list with filters + pagination | 8 |
| Run detail: header actions, error block, prompt (collapsible + first-user-message preference), transcript (read-only MessageList via `chat.history`), metadata (model/tokens/delivery/session/next) | 10 |
| Edit form Basics | 11 + 12 |
| Edit form Delivery (picker with channels/accounts/failure destination) | 13 |
| Edit form Agent execution (model/fallbacks/timeout/thinking/lightContext) | 14 |
| Tools allowlist | 15 |
| Failure alerts | 16 |
| Advanced (deleteAfterRun/wakeMode/agentId) | 16 |
| Create-form defaults | 16 |
| Data flow: cron.list, cron.runs, chat.history, channels.status, tools.catalog, models.list | 7, 8, 10, 13, 15 |
| Types (full OpenClaw model) | 1 |
| File structure decomposition | 1–16 (tasks create exactly the files listed in the spec) |
| Edge case: cron running | 5 (indicator), 17 (synthetic in-progress row deferred as `Task 17.x` — NOTE: not implemented in v1; see below) |
| Edge case: missing sessionId | 10 (RunTranscript shows "No transcript available") |
| Edge case: session fetch errors | 10 (error banner + retry) |
| Edge case: self-deleting cron | 17 |
| Edge case: user deletes job while in State B | 17 |
| Edge case: many runs | 8 (load-more) |
| Edge case: delivery failed but run succeeded | 5 (card badge), 10 (metadata delivery block) |
| Edge case: container asleep | inherited from useGateway; not panel-specific |
| Edge case: no agents | 17 |
| Edge case: invalid cron expression | 12 (live validation) |
| Edge case: pre-existing non-isolated jobs | 1 (type retains sessionTarget) + 16 (edit form doesn't expose it; cron.update is a patch so field is preserved) |
| Edge case: job prompt edited after run | 10 (displayedPrompt prefers first user message from transcript) |
| Auto-refresh cadence | 17 |
| Error banners | 17 |
| `autoScroll` on MessageList | 2 |
| No backend changes | ✓ (no backend files modified in any task) |

### Placeholder scan

- No "TBD", "TODO", or "add appropriate …" patterns.
- Every code-step has inline code (types, test body, or implementation).
- Every shell step has an exact command and expected result.

### Known deferrals documented

- The "synthetic in-progress run row at top of State B runs list" noted in the spec edge-cases is **not** implemented by this plan; the running indicator on the job card (Task 5) is sufficient for v1. The State B row would require merging in-memory running state with fetched runs, which is more complex than the value warrants for v1. Adding a tracked follow-up below.

### Follow-ups (out of scope for this plan)

- Synthetic "in-progress" run row at the top of State B's runs list while `runningAtMs` is set.
- Natural-language → cron-expression helper in `SchedulePicker`.
- Global runs inbox as a separate entry point (per spec non-goals, this is explicitly deferred).
