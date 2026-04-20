# Exec Approval Card Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the text-based `/approve <id>` fallback with an inline Claude-Code-style approval card (Allow once / Trust / Deny) that renders wherever the agent is running a tool, so commands don't silently stall in `allowlist` mode.

**Architecture:** Extend the existing `ToolUse` lifecycle with two new statuses (`"pending-approval"`, `"denied"`) and a `pendingApproval` field. `useAgentChat` subscribes to OpenClaw's `exec.approval.requested` event and mutates the matching ToolUse; `ToolPill` renders a new `ApprovalCard` component for pending state. Decisions post back via `sendReq("exec.approval.resolve", {id, decision})` — OpenClaw handles persistence server-side.

**Tech Stack:** Next.js 16, React 19, Tailwind v4, shadcn/ui, Vitest + React Testing Library.

**Spec:** [`docs/superpowers/specs/2026-04-18-exec-approval-card-design.md`](../specs/2026-04-18-exec-approval-card-design.md)

---

## File Structure

**New:**
- `apps/frontend/src/components/chat/ApprovalCard.tsx` — the 3-button card UI.
- `apps/frontend/tests/unit/components/chat/ApprovalCard.test.tsx` — card rendering + decision click tests.

**Modified:**
- `apps/frontend/src/components/chat/MessageList.tsx` — extend `ToolUse` type, export `ApprovalRequest`/`ToolUse`, wire `ApprovalCard` into `ToolPill` render branch, add `onDecide` prop plumbing through `MessageListProps` → `ToolUseIndicator` → `ToolPill`.
- `apps/frontend/src/hooks/useAgentChat.ts` — subscribe to `exec.approval.requested` / `exec.approval.resolved` via `onEvent`; expose `resolveApproval(id, decision)` in the hook's return value.
- `apps/frontend/src/components/chat/AgentChatWindow.tsx` — pass `resolveApproval` from the hook down to `MessageList` via a new prop.
- `apps/frontend/tests/unit/components/chat/MessageList.test.tsx` — add a test asserting pending-approval ToolUses render the ApprovalCard.

**Conditional (verified empirically in Task 7):**
- `apps/backend/core/gateway/connection_pool.py` — if the event arrives wrapped as an agent-stream event, add passthrough case.

---

## Task 1: Extend ToolUse type and export ApprovalRequest

**Files:**
- Modify: `apps/frontend/src/components/chat/MessageList.tsx:19-34`

Extend the `ToolUse` interface with two new statuses and a `pendingApproval` field. Add and export a new `ApprovalRequest` type. Export `ToolUse` and `ApprovalRequest` so `ApprovalCard` and `useAgentChat` can import them. No behavior change yet — ToolPill won't render the new states until Task 5.

- [ ] **Step 1: Modify the type definitions**

Replace lines 12-35 of `apps/frontend/src/components/chat/MessageList.tsx` with:

```typescript
export interface ToolResultBlock {
  type: string;
  text?: string;
  bytes?: number;
  omitted?: boolean;
}

export type ExecApprovalDecision = "allow-once" | "allow-always" | "deny";

export interface ApprovalRequest {
  /** Approval ID issued by OpenClaw. Used as the key when posting exec.approval.resolve. */
  id: string;
  /** Raw command line as the agent would execute it. */
  command: string;
  /** Parsed argv; absent when the request came through host=node with a wrapped form. */
  commandArgv?: string[];
  /** Where the command would run. */
  host: "gateway" | "node" | "sandbox";
  /** Working directory for the command. */
  cwd?: string;
  /** Resolved absolute path of the executable (post wrapper-unwrap) — what Trust persists. */
  resolvedPath?: string;
  /** OpenClaw agent ID that issued the exec. */
  agentId?: string;
  /** Session identifier: used for audit display only. */
  sessionKey?: string;
  /** Which decisions the server will accept — usually all three, but "allow-always" may be absent when policy is ask=always. */
  allowedDecisions: ExecApprovalDecision[];
  /** Server-side expiry timestamp in ms. Not rendered as a countdown per product decision. */
  expiresAtMs?: number;
}

export interface ToolUse {
  tool: string;
  toolCallId?: string;
  status: "running" | "done" | "error" | "pending-approval" | "denied";
  args?: Record<string, unknown>;
  result?: ToolResultBlock[];
  meta?: string;
  /** Set when status === "pending-approval". Cleared once the user decides. */
  pendingApproval?: ApprovalRequest;
  /** Set when status !== "pending-approval" and the ToolUse was previously resolved. */
  resolvedDecision?: ExecApprovalDecision;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  thinking?: string;
  model?: string;
  toolUses?: ToolUse[];
}
```

- [ ] **Step 2: Run the type check to verify nothing broke**

Run: `cd apps/frontend && pnpm tsc --noEmit`
Expected: PASS. No errors — this is purely additive.

- [ ] **Step 3: Run existing MessageList tests**

Run: `cd apps/frontend && pnpm test --run tests/unit/components/chat/MessageList.test.tsx`
Expected: all tests PASS (no behavior change yet).

- [ ] **Step 4: Commit**

```bash
git add apps/frontend/src/components/chat/MessageList.tsx
git commit -m "$(cat <<'EOF'
feat(chat): extend ToolUse with pending-approval/denied states

Add ApprovalRequest type and pendingApproval field on ToolUse. Export
both so useAgentChat and the new ApprovalCard can share the shape.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Scaffold ApprovalCard component — failing test first

**Files:**
- Create: `apps/frontend/tests/unit/components/chat/ApprovalCard.test.tsx`
- Create: `apps/frontend/src/components/chat/ApprovalCard.tsx`

Start with a failing test that asserts the card renders the command text. Then stub the component just enough to make the test pass.

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/tests/unit/components/chat/ApprovalCard.test.tsx`:

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ApprovalCard } from "@/components/chat/ApprovalCard";
import type { ApprovalRequest } from "@/components/chat/MessageList";

const baseRequest: ApprovalRequest = {
  id: "approval-123",
  command: "whoami",
  commandArgv: ["whoami"],
  host: "node",
  cwd: "/Users/prasiddha",
  resolvedPath: "/usr/bin/whoami",
  agentId: "main",
  sessionKey: "personal.user_abc.main",
  allowedDecisions: ["allow-once", "allow-always", "deny"],
};

describe("ApprovalCard", () => {
  it("renders the command text as the primary line", () => {
    render(<ApprovalCard pending={baseRequest} onDecide={vi.fn()} />);
    expect(screen.getByText("whoami")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/frontend && pnpm test --run tests/unit/components/chat/ApprovalCard.test.tsx`
Expected: FAIL with "Cannot find module '@/components/chat/ApprovalCard'".

- [ ] **Step 3: Create the minimal ApprovalCard component**

Create `apps/frontend/src/components/chat/ApprovalCard.tsx`:

```tsx
import * as React from "react";
import type { ApprovalRequest, ExecApprovalDecision } from "./MessageList";

export interface ApprovalCardProps {
  pending: ApprovalRequest;
  onDecide: (decision: ExecApprovalDecision) => Promise<void>;
}

export function ApprovalCard({ pending }: ApprovalCardProps) {
  return (
    <div className="my-2 max-w-xl rounded-md border border-[#e0dbd0] bg-[#faf7f2] p-3 text-sm">
      <div className="font-mono text-[#1a1a1a]">{pending.command}</div>
    </div>
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd apps/frontend && pnpm test --run tests/unit/components/chat/ApprovalCard.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/components/chat/ApprovalCard.tsx apps/frontend/tests/unit/components/chat/ApprovalCard.test.tsx
git commit -m "$(cat <<'EOF'
feat(chat): scaffold ApprovalCard component

Minimal card rendering the command text. Layout + buttons in follow-up.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Full card layout — host badge, cwd, agent, 3 buttons, details expander

**Files:**
- Modify: `apps/frontend/src/components/chat/ApprovalCard.tsx`
- Modify: `apps/frontend/tests/unit/components/chat/ApprovalCard.test.tsx`

- [ ] **Step 1: Add the failing tests**

Append to `apps/frontend/tests/unit/components/chat/ApprovalCard.test.tsx`:

```tsx
import { fireEvent } from "@testing-library/react";

describe("ApprovalCard layout", () => {
  it("renders host badge, cwd, and agent name", () => {
    render(<ApprovalCard pending={baseRequest} onDecide={vi.fn()} />);
    expect(screen.getByText("node")).toBeInTheDocument();
    expect(screen.getByText("/Users/prasiddha")).toBeInTheDocument();
    expect(screen.getByText("main")).toBeInTheDocument();
  });

  it("renders all three decision buttons when allowedDecisions includes them all", () => {
    render(<ApprovalCard pending={baseRequest} onDecide={vi.fn()} />);
    expect(screen.getByRole("button", { name: /allow once/i })).toBeEnabled();
    expect(screen.getByRole("button", { name: /trust/i })).toBeEnabled();
    expect(screen.getByRole("button", { name: /deny/i })).toBeEnabled();
  });

  it("disables Trust when allow-always is not in allowedDecisions", () => {
    const r: ApprovalRequest = { ...baseRequest, allowedDecisions: ["allow-once", "deny"] };
    render(<ApprovalCard pending={r} onDecide={vi.fn()} />);
    expect(screen.getByRole("button", { name: /trust/i })).toBeDisabled();
  });

  it("calls onDecide with the correct decision on click", async () => {
    const onDecide = vi.fn().mockResolvedValue(undefined);
    render(<ApprovalCard pending={baseRequest} onDecide={onDecide} />);
    fireEvent.click(screen.getByRole("button", { name: /allow once/i }));
    expect(onDecide).toHaveBeenCalledWith("allow-once");
  });

  it("shows resolvedPath and argv when Details is toggled open", () => {
    render(<ApprovalCard pending={baseRequest} onDecide={vi.fn()} />);
    expect(screen.queryByText("/usr/bin/whoami")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /details/i }));
    expect(screen.getByText("/usr/bin/whoami")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/frontend && pnpm test --run tests/unit/components/chat/ApprovalCard.test.tsx`
Expected: FAIL — new assertions fail (buttons not rendered, no Details toggle, etc.).

- [ ] **Step 3: Implement the full layout**

Replace `apps/frontend/src/components/chat/ApprovalCard.tsx` with:

```tsx
import * as React from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import type { ApprovalRequest, ExecApprovalDecision } from "./MessageList";

export interface ApprovalCardProps {
  pending: ApprovalRequest;
  onDecide: (decision: ExecApprovalDecision) => Promise<void>;
}

const HOST_LABEL: Record<ApprovalRequest["host"], string> = {
  gateway: "container",
  node: "node",
  sandbox: "sandbox",
};

export function ApprovalCard({ pending, onDecide }: ApprovalCardProps) {
  const [detailsOpen, setDetailsOpen] = React.useState(false);
  const allowsOnce = pending.allowedDecisions.includes("allow-once");
  const allowsAlways = pending.allowedDecisions.includes("allow-always");
  const allowsDeny = pending.allowedDecisions.includes("deny");
  const handle = (d: ExecApprovalDecision) => () => { void onDecide(d); };
  const trustScopeLine = pending.resolvedPath
    ? `Trust will always allow ${pending.resolvedPath} on this ${pending.host === "node" ? "Mac" : "agent"} (any arguments).`
    : "Trust will always allow this command (any arguments).";

  return (
    <div className="my-2 max-w-xl rounded-md border border-[#e0dbd0] bg-[#faf7f2] p-3 text-sm">
      <div className="flex items-start justify-between gap-2">
        <div className="font-mono text-[#1a1a1a] break-all">{pending.command}</div>
        <span className="inline-flex items-center px-2 py-0.5 text-xs rounded bg-[#e8e3d9] text-[#302d28]">
          {HOST_LABEL[pending.host]}
        </span>
      </div>
      {pending.cwd && <div className="mt-1 text-xs text-[#8a8578]">{pending.cwd}</div>}
      {pending.agentId && <div className="text-xs text-[#8a8578]">{pending.agentId}</div>}

      <div className="mt-3 flex gap-2">
        <Button size="sm" variant="default" disabled={!allowsOnce} onClick={handle("allow-once")}>
          Allow once
        </Button>
        <Button size="sm" variant="secondary" disabled={!allowsAlways} onClick={handle("allow-always")}>
          Trust
        </Button>
        <Button size="sm" variant="ghost" disabled={!allowsDeny} onClick={handle("deny")}>
          Deny
        </Button>
      </div>

      <button
        type="button"
        onClick={() => setDetailsOpen((v) => !v)}
        className="mt-3 inline-flex items-center gap-1 text-xs text-[#8a8578] hover:text-[#302d28]"
      >
        {detailsOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        Details
      </button>
      {detailsOpen && (
        <div className="mt-2 space-y-1 text-xs text-[#302d28]">
          {pending.resolvedPath && (
            <div>
              <span className="text-[#8a8578]">Resolves to </span>
              <span className="font-mono">{pending.resolvedPath}</span>
            </div>
          )}
          {pending.commandArgv && (
            <div>
              <span className="text-[#8a8578]">argv </span>
              <span className="font-mono">{JSON.stringify(pending.commandArgv)}</span>
            </div>
          )}
          {pending.sessionKey && (
            <div>
              <span className="text-[#8a8578]">Session </span>
              <span className="font-mono">{pending.sessionKey}</span>
            </div>
          )}
          {allowsAlways && <div className="text-[#8a8578] pt-1">{trustScopeLine}</div>}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/frontend && pnpm test --run tests/unit/components/chat/ApprovalCard.test.tsx`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/components/chat/ApprovalCard.tsx apps/frontend/tests/unit/components/chat/ApprovalCard.test.tsx
git commit -m "$(cat <<'EOF'
feat(chat): full ApprovalCard layout + decision buttons

Host badge, cwd, agent line, 3 buttons (disabled when not in
allowedDecisions), details expander with resolvedPath + argv.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Spinner + inline retry on RPC failure

**Files:**
- Modify: `apps/frontend/src/components/chat/ApprovalCard.tsx`
- Modify: `apps/frontend/tests/unit/components/chat/ApprovalCard.test.tsx`

- [ ] **Step 1: Write the failing test**

Append to `apps/frontend/tests/unit/components/chat/ApprovalCard.test.tsx`:

```tsx
import { waitFor } from "@testing-library/react";

describe("ApprovalCard RPC states", () => {
  it("shows spinner on the clicked button while the RPC is pending", async () => {
    let resolveRpc: () => void = () => {};
    const onDecide = vi.fn().mockImplementation(() => new Promise<void>((r) => { resolveRpc = r; }));
    render(<ApprovalCard pending={baseRequest} onDecide={onDecide} />);
    fireEvent.click(screen.getByRole("button", { name: /allow once/i }));
    expect(screen.getByRole("button", { name: /allow once/i })).toHaveAttribute("aria-busy", "true");
    resolveRpc();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /allow once/i })).not.toHaveAttribute("aria-busy", "true"),
    );
  });

  it("shows inline error and retry when onDecide rejects", async () => {
    const onDecide = vi.fn()
      .mockRejectedValueOnce(new Error("network"))
      .mockResolvedValueOnce(undefined);
    render(<ApprovalCard pending={baseRequest} onDecide={onDecide} />);
    fireEvent.click(screen.getByRole("button", { name: /allow once/i }));
    await waitFor(() =>
      expect(screen.getByText(/couldn't send decision/i)).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    await waitFor(() => expect(onDecide).toHaveBeenCalledTimes(2));
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/frontend && pnpm test --run tests/unit/components/chat/ApprovalCard.test.tsx`
Expected: FAIL — no spinner state, no error UI.

- [ ] **Step 3: Add spinner + error state to the component**

Replace the `ApprovalCard` function body with:

```tsx
export function ApprovalCard({ pending, onDecide }: ApprovalCardProps) {
  const [detailsOpen, setDetailsOpen] = React.useState(false);
  const [pendingDecision, setPendingDecision] = React.useState<ExecApprovalDecision | null>(null);
  const [errorMsg, setErrorMsg] = React.useState<string | null>(null);
  const [lastFailed, setLastFailed] = React.useState<ExecApprovalDecision | null>(null);

  const allowsOnce = pending.allowedDecisions.includes("allow-once");
  const allowsAlways = pending.allowedDecisions.includes("allow-always");
  const allowsDeny = pending.allowedDecisions.includes("deny");

  const trustScopeLine = pending.resolvedPath
    ? `Trust will always allow ${pending.resolvedPath} on this ${pending.host === "node" ? "Mac" : "agent"} (any arguments).`
    : "Trust will always allow this command (any arguments).";

  const submit = React.useCallback(
    async (decision: ExecApprovalDecision) => {
      setPendingDecision(decision);
      setErrorMsg(null);
      try {
        await onDecide(decision);
        setLastFailed(null);
      } catch (e) {
        setErrorMsg(e instanceof Error ? e.message : "Couldn't send decision");
        setLastFailed(decision);
      } finally {
        setPendingDecision(null);
      }
    },
    [onDecide],
  );

  return (
    <div className="my-2 max-w-xl rounded-md border border-[#e0dbd0] bg-[#faf7f2] p-3 text-sm">
      <div className="flex items-start justify-between gap-2">
        <div className="font-mono text-[#1a1a1a] break-all">{pending.command}</div>
        <span className="inline-flex items-center px-2 py-0.5 text-xs rounded bg-[#e8e3d9] text-[#302d28]">
          {HOST_LABEL[pending.host]}
        </span>
      </div>
      {pending.cwd && <div className="mt-1 text-xs text-[#8a8578]">{pending.cwd}</div>}
      {pending.agentId && <div className="text-xs text-[#8a8578]">{pending.agentId}</div>}

      <div className="mt-3 flex gap-2">
        <Button
          size="sm"
          variant="default"
          disabled={!allowsOnce || pendingDecision !== null}
          aria-busy={pendingDecision === "allow-once"}
          onClick={() => submit("allow-once")}
        >
          {pendingDecision === "allow-once" ? "Sending…" : "Allow once"}
        </Button>
        <Button
          size="sm"
          variant="secondary"
          disabled={!allowsAlways || pendingDecision !== null}
          aria-busy={pendingDecision === "allow-always"}
          onClick={() => submit("allow-always")}
        >
          {pendingDecision === "allow-always" ? "Sending…" : "Trust"}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          disabled={!allowsDeny || pendingDecision !== null}
          aria-busy={pendingDecision === "deny"}
          onClick={() => submit("deny")}
        >
          {pendingDecision === "deny" ? "Sending…" : "Deny"}
        </Button>
      </div>

      {errorMsg && (
        <div className="mt-2 text-xs text-[#b42318] flex items-center gap-2">
          <span>Couldn't send decision: {errorMsg}.</span>
          {lastFailed && (
            <button
              type="button"
              className="underline"
              onClick={() => submit(lastFailed)}
              disabled={pendingDecision !== null}
            >
              Retry
            </button>
          )}
        </div>
      )}

      <button
        type="button"
        onClick={() => setDetailsOpen((v) => !v)}
        className="mt-3 inline-flex items-center gap-1 text-xs text-[#8a8578] hover:text-[#302d28]"
      >
        {detailsOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        Details
      </button>
      {detailsOpen && (
        <div className="mt-2 space-y-1 text-xs text-[#302d28]">
          {pending.resolvedPath && (
            <div>
              <span className="text-[#8a8578]">Resolves to </span>
              <span className="font-mono">{pending.resolvedPath}</span>
            </div>
          )}
          {pending.commandArgv && (
            <div>
              <span className="text-[#8a8578]">argv </span>
              <span className="font-mono">{JSON.stringify(pending.commandArgv)}</span>
            </div>
          )}
          {pending.sessionKey && (
            <div>
              <span className="text-[#8a8578]">Session </span>
              <span className="font-mono">{pending.sessionKey}</span>
            </div>
          )}
          {allowsAlways && <div className="text-[#8a8578] pt-1">{trustScopeLine}</div>}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run all ApprovalCard tests**

Run: `cd apps/frontend && pnpm test --run tests/unit/components/chat/ApprovalCard.test.tsx`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/components/chat/ApprovalCard.tsx apps/frontend/tests/unit/components/chat/ApprovalCard.test.tsx
git commit -m "$(cat <<'EOF'
feat(chat): spinner + inline retry on ApprovalCard RPC failure

Clicked button shows aria-busy during submission. On reject, inline
error with a retry link rebinds the same decision.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Subscribe useAgentChat to exec.approval.* events + expose resolveApproval

**Files:**
- Modify: `apps/frontend/src/hooks/useAgentChat.ts`

The approval events come through `onEvent` (not `onChatMessage`). We need to listen for them, mutate the matching ToolUse, and expose a `resolveApproval` function that `ApprovalCard` eventually calls via the prop chain.

**Matching strategy:** the `exec.approval.requested` payload should carry a correlation field that ties the approval to a prior `tool_start`. We don't know the exact field name empirically yet — the code below tries `toolCallId`, falls back to `approvalCorrelationId`, then falls back to attaching to the most-recent running `exec` ToolUse in the current message. Task 7 verifies the real field and narrows the matching logic.

- [ ] **Step 1: Add event subscription and resolveApproval to the hook**

Read `apps/frontend/src/hooks/useAgentChat.ts` to locate the existing `onChatMessage` subscription (around line 230). Add the new subscription just after it. Also expose `resolveApproval` in the hook's return object.

At the top of the file, add near existing imports from `useGateway`:

```typescript
import type { ApprovalRequest, ExecApprovalDecision, ToolUse } from "@/components/chat/MessageList";
```

Find the destructure of `useGateway()` (it already pulls `sendReq`, `onChatMessage`, etc.) and ensure `onEvent` is included. Example (match existing import/destructure style):

```typescript
const { onChatMessage, onEvent, sendReq, isConnected } = useGateway();
```

Add a new `useEffect` after the `onChatMessage` effect (around line 392):

```typescript
// ---- Approval event handler ----
useEffect(() => {
  const unsubRequested = onEvent((eventName, data) => {
    if (eventName !== "exec.approval.requested") return;
    const payload = data as {
      id?: string;
      request?: {
        command?: string;
        commandArgv?: string[];
        host?: ApprovalRequest["host"];
        cwd?: string;
        resolvedPath?: string;
        agentId?: string;
        sessionKey?: string;
        allowedDecisions?: ExecApprovalDecision[];
        toolCallId?: string;
        approvalCorrelationId?: string;
      };
      createdAtMs?: number;
      expiresAtMs?: number;
    };
    if (!payload?.id || !payload.request?.command) return;

    const req: ApprovalRequest = {
      id: payload.id,
      command: payload.request.command,
      commandArgv: payload.request.commandArgv,
      host: payload.request.host ?? "gateway",
      cwd: payload.request.cwd,
      resolvedPath: payload.request.resolvedPath,
      agentId: payload.request.agentId,
      sessionKey: payload.request.sessionKey,
      allowedDecisions: payload.request.allowedDecisions ?? ["allow-once", "deny"],
      expiresAtMs: payload.expiresAtMs,
    };
    const correlation = payload.request.toolCallId ?? payload.request.approvalCorrelationId;

    if (!currentAssistantIdRef.current) return;
    setMessages((prev) =>
      prev.map((m) => {
        if (m.id !== currentAssistantIdRef.current) return m;
        const existing = m.toolUses ?? [];
        // Try to match an in-flight exec ToolUse by correlation id; fall back
        // to the most recent running exec.
        let matched = false;
        const next: ToolUse[] = existing.map((t) => {
          if (matched) return t;
          const idMatch = correlation && t.toolCallId === correlation;
          const fallbackMatch =
            !correlation && t.tool === "exec" && t.status === "running";
          if (idMatch || fallbackMatch) {
            matched = true;
            return { ...t, status: "pending-approval", pendingApproval: req };
          }
          return t;
        });
        if (!matched) {
          // Orphan: attach as a new ToolUse so the user can still act.
          next.push({
            tool: "exec",
            toolCallId: correlation,
            status: "pending-approval",
            pendingApproval: req,
          });
        }
        return { ...m, toolUses: next };
      }),
    );
  });

  const unsubResolved = onEvent((eventName, data) => {
    if (eventName !== "exec.approval.resolved") return;
    const payload = data as { id?: string; decision?: ExecApprovalDecision };
    if (!payload?.id) return;

    setMessages((prev) =>
      prev.map((m) => {
        if (!m.toolUses?.some((t) => t.pendingApproval?.id === payload.id)) return m;
        const next = m.toolUses.map((t) => {
          if (t.pendingApproval?.id !== payload.id) return t;
          const nextStatus: ToolUse["status"] =
            payload.decision === "deny" ? "denied" : "running";
          return {
            ...t,
            status: nextStatus,
            pendingApproval: undefined,
            resolvedDecision: payload.decision,
          };
        });
        return { ...m, toolUses: next };
      }),
    );
  });

  return () => {
    unsubRequested();
    unsubResolved();
  };
}, [onEvent]);
```

Add `resolveApproval` to the hook body (before the return statement at the end of `useAgentChat`):

```typescript
const resolveApproval = React.useCallback(
  async (id: string, decision: ExecApprovalDecision): Promise<void> => {
    await sendReq("exec.approval.resolve", { id, decision });
  },
  [sendReq],
);
```

Add `resolveApproval` to the hook's return object (merge with existing returned values):

```typescript
return {
  // ...existing returned values
  resolveApproval,
};
```

- [ ] **Step 2: Type-check**

Run: `cd apps/frontend && pnpm tsc --noEmit`
Expected: PASS.

- [ ] **Step 3: Run existing useAgentChat tests (if any)**

Run: `cd apps/frontend && pnpm test --run src/hooks`
Expected: all existing tests PASS. No new tests in this step — behavior is purely additive and covered by the Chrome MCP E2E in Task 8.

- [ ] **Step 4: Commit**

```bash
git add apps/frontend/src/hooks/useAgentChat.ts
git commit -m "$(cat <<'EOF'
feat(chat): subscribe useAgentChat to exec.approval.* events

exec.approval.requested attaches a pendingApproval to the in-flight
exec ToolUse (or creates an orphan). exec.approval.resolved clears
it. Hook now exposes resolveApproval(id, decision) which posts the
exec.approval.resolve RPC.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Wire ApprovalCard into ToolPill + handle denied/resolved chip states

**Files:**
- Modify: `apps/frontend/src/components/chat/MessageList.tsx`
- Modify: `apps/frontend/src/components/chat/AgentChatWindow.tsx`
- Modify: `apps/frontend/tests/unit/components/chat/MessageList.test.tsx`

Add a prop `onDecide: (id, decision) => Promise<void>` that threads from `MessageList` → `ToolUseIndicator` → `ToolPill`. When a ToolUse is `status === "pending-approval"`, render `<ApprovalCard>` inline instead of the pill. When `status === "denied"`, render a red chip. When `status === "done"` or `"running"` with a `resolvedDecision` set, render a tiny chip suffix (`· allow-once`).

- [ ] **Step 1: Write the failing MessageList test**

Append to `apps/frontend/tests/unit/components/chat/MessageList.test.tsx`:

```tsx
import type { ToolUse, ApprovalRequest } from '@/components/chat/MessageList';

describe('MessageList approval rendering', () => {
  const pendingApproval: ApprovalRequest = {
    id: 'approval-xyz',
    command: 'whoami',
    host: 'node',
    allowedDecisions: ['allow-once', 'allow-always', 'deny'],
  };

  const pendingToolUse: ToolUse = {
    tool: 'exec',
    toolCallId: 'call-1',
    status: 'pending-approval',
    pendingApproval,
  };

  const deniedToolUse: ToolUse = {
    tool: 'exec',
    toolCallId: 'call-2',
    status: 'denied',
    resolvedDecision: 'deny',
  };

  it('renders ApprovalCard when a tool is pending approval', () => {
    render(
      <MessageList
        messages={[
          { id: 'a1', role: 'assistant', content: '', toolUses: [pendingToolUse] },
        ]}
        onDecide={vi.fn()}
      />,
    );
    // ApprovalCard shows the command + 3 buttons
    expect(screen.getByText('whoami')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /allow once/i })).toBeInTheDocument();
  });

  it('renders a denied chip when a tool was denied', () => {
    render(
      <MessageList
        messages={[
          { id: 'a2', role: 'assistant', content: '', toolUses: [deniedToolUse] },
        ]}
        onDecide={vi.fn()}
      />,
    );
    expect(screen.getByText(/denied/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd apps/frontend && pnpm test --run tests/unit/components/chat/MessageList.test.tsx`
Expected: FAIL — MessageList has no `onDecide` prop yet; no pending-approval rendering.

- [ ] **Step 3: Add onDecide prop + wire ApprovalCard into ToolPill**

In `apps/frontend/src/components/chat/MessageList.tsx`:

1. Add an import at the top (after existing imports):
```tsx
import { ApprovalCard } from "./ApprovalCard";
```

2. Extend the props interface (around line 37-43):
```typescript
export interface MessageListProps {
  messages: Message[];
  isTyping?: boolean;
  agentName?: string;
  onRetry?: (assistantMsgId: string) => void;
  onOpenFile?: (path: string) => void;
  /** Called when the user clicks Allow once / Trust / Deny on a pending approval card. */
  onDecide?: (approvalId: string, decision: ExecApprovalDecision) => Promise<void>;
}
```

3. Add `TOOL_STYLES` entries for the new statuses. Find the `TOOL_STYLES` record (around line 180-190) and add the two new cases. Example (preserve the colors already in use for other statuses):

```typescript
"pending-approval": {
  pill: "bg-[#fff7ea] text-[#6b4a00] border-[#f0d7a0]",
  dot: "bg-[#c38a00]",
},
denied: {
  pill: "bg-[#fdecec] text-[#8a1f1f] border-[#f1c0c0]",
  dot: "bg-[#b42318]",
},
```

4. Modify `ToolPill` (around line 194) to accept `onDecide` and render `ApprovalCard` for pending state. Replace the component with:

```tsx
function ToolPill({
  t,
  onDecide,
}: {
  t: ToolUse;
  onDecide?: MessageListProps["onDecide"];
}) {
  const [open, setOpen] = React.useState(false);
  const s = TOOL_STYLES[t.status];
  const hasDetails = !!(t.args || t.result || t.meta);

  if (t.status === "pending-approval" && t.pendingApproval && onDecide) {
    return (
      <ApprovalCard
        pending={t.pendingApproval}
        onDecide={(decision) => onDecide(t.pendingApproval!.id, decision)}
      />
    );
  }

  if (t.status === "denied") {
    return (
      <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium border bg-[#fdecec] text-[#8a1f1f] border-[#f1c0c0]">
        <span className="w-1.5 h-1.5 rounded-full bg-[#b42318]" />
        <span>{t.tool}</span>
        <span>· denied</span>
      </div>
    );
  }

  const decisionSuffix = t.resolvedDecision && t.status === "done"
    ? ` · ${t.resolvedDecision}`
    : "";

  return (
    <div className="inline-block">
      <button
        type="button"
        onClick={() => hasDetails && setOpen((v) => !v)}
        disabled={!hasDetails}
        className={cn(
          "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium border transition-colors",
          s.pill,
          hasDetails ? "cursor-pointer hover:brightness-95" : "cursor-default",
        )}
        aria-expanded={open}
      >
        <span className={cn("w-1.5 h-1.5 rounded-full", s.dot)} />
        <span>{t.tool}</span>
        {t.status === "error" && <span>failed</span>}
        {decisionSuffix && <span>{decisionSuffix}</span>}
        {hasDetails &&
          (open ? (
            <ChevronDown className="h-3 w-3 opacity-70" />
          ) : (
            <ChevronRight className="h-3 w-3 opacity-70" />
          ))}
      </button>
      {open && hasDetails && (
        <div className="mt-1.5 max-w-xl rounded-md border border-[#e0dbd0] bg-[#faf7f2] p-2 text-xs space-y-2">
          {t.meta && (
            <div className="text-[#8a8578]">
              <span className="font-medium text-[#302d28]">target:</span> {t.meta}
            </div>
          )}
          {t.args && Object.keys(t.args).length > 0 && (
            <div>
              <div className="font-medium text-[#302d28] mb-0.5">input</div>
              <pre className="whitespace-pre-wrap break-words text-[#302d28] bg-[#f3efe6] rounded px-2 py-1 max-h-48 overflow-auto">
                {JSON.stringify(t.args, null, 2)}
              </pre>
            </div>
          )}
          {renderToolResult(t.result) && (
            <div>
              <div className="font-medium text-[#302d28] mb-0.5">
                {t.status === "error" ? "error" : "output"}
              </div>
              <pre className="whitespace-pre-wrap break-words text-[#302d28] bg-[#f3efe6] rounded px-2 py-1 max-h-48 overflow-auto">
                {renderToolResult(t.result)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
```

5. Modify `ToolUseIndicator` (around line 253-262) to thread `onDecide`:

```tsx
function ToolUseIndicator({
  toolUses,
  onDecide,
}: {
  toolUses: ToolUse[];
  onDecide?: MessageListProps["onDecide"];
}) {
  if (toolUses.length === 0) return null;
  return (
    <div className="mb-3 flex flex-wrap gap-2 items-start">
      {toolUses.map((t, i) => (
        <ToolPill key={t.toolCallId ?? `${t.tool}-${i}`} t={t} onDecide={onDecide} />
      ))}
    </div>
  );
}
```

6. Find where `ToolUseIndicator` is called (around line 385) and pass `onDecide` through. In the `messages.map` body:

```tsx
{msg.toolUses && msg.toolUses.length > 0 && (
  <ToolUseIndicator toolUses={msg.toolUses} onDecide={onDecide} />
)}
```

7. Update `MessageList` function signature (around line 330) to destructure `onDecide`:

```tsx
export function MessageList({ messages, isTyping, agentName, onRetry, onOpenFile, onDecide }: MessageListProps) {
```

- [ ] **Step 4: Wire resolveApproval through AgentChatWindow**

In `apps/frontend/src/components/chat/AgentChatWindow.tsx`, find where `useAgentChat` is called and pull `resolveApproval` from its return value. Pass it through to `<MessageList>` as `onDecide`. Example:

```tsx
const { messages, resolveApproval, /* existing fields */ } = useAgentChat({ /* existing args */ });

// ...

<MessageList
  messages={messages}
  onDecide={resolveApproval}
  /* existing props */
/>
```

- [ ] **Step 5: Run MessageList tests**

Run: `cd apps/frontend && pnpm test --run tests/unit/components/chat/MessageList.test.tsx`
Expected: all PASS.

- [ ] **Step 6: Run full frontend test suite**

Run: `cd apps/frontend && pnpm test`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/frontend/src/components/chat/MessageList.tsx apps/frontend/src/components/chat/AgentChatWindow.tsx apps/frontend/tests/unit/components/chat/MessageList.test.tsx
git commit -m "$(cat <<'EOF'
feat(chat): render ApprovalCard inline + denied/resolved chip states

Thread resolveApproval from useAgentChat -> AgentChatWindow ->
MessageList -> ToolUseIndicator -> ToolPill. Pending-approval status
renders ApprovalCard; denied renders a red chip; resolved running/done
gets a decision suffix (· allow-once / · allow-always).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Verify event forwarding empirically

**Files:**
- Possibly modify: `apps/backend/core/gateway/connection_pool.py`

Before wiring anything on the backend, trigger a real approval in dev and capture the event. If it already reaches the frontend, no backend change needed.

- [ ] **Step 1: Start frontend in dev mode against dev.isol8.co**

Run: `cd apps/frontend && pnpm run dev`
Open `http://localhost:3000/chat` in a browser, sign in, wait for container to start.

- [ ] **Step 2: Instrument a dev-only console.log in useAgentChat**

Temporarily add at the top of the `exec.approval.requested` handler in `useAgentChat.ts`:

```typescript
console.log("[DEV] exec.approval.requested raw:", JSON.stringify(data, null, 2));
```

- [ ] **Step 3: Trigger an approval**

In the chat, ask the agent: "Call exec with command=['whoami'] and host='node'". The agent should emit an `exec.approval.requested` event because `whoami` is not in the default allowlist.

- [ ] **Step 4: Inspect the console**

Open Chrome DevTools, look for `[DEV] exec.approval.requested raw:` log. Note:
- Does it fire at all? (If not, check the backend forwarding — Step 5.)
- What is the exact correlation field name? (`toolCallId`, `approvalCorrelationId`, or absent?)
- What's in `request.allowedDecisions`?

- [ ] **Step 5 (conditional): Add backend passthrough**

If the event does NOT fire in the browser, check backend logs:
```bash
aws logs filter-log-events \
  --log-group-name "/ecs/isol8-dev" \
  --profile isol8-admin --region us-east-1 \
  --start-time $(python3 -c "import time; print(int((time.time()-300)*1000))") \
  --filter-pattern '"exec.approval"' \
  --max-items 10 --query 'events[].message' --output text
```

If the backend DID receive the event from the container but didn't forward it, open `apps/backend/core/gateway/connection_pool.py`, locate the `_handle_message` function (around line 586), and trace why the event was dropped. The fix is typically to add a passthrough case in `_transform_agent_event` or ensure top-level events bypass that filter.

- [ ] **Step 6: Narrow the correlation matching in useAgentChat**

Based on the actual field name observed in Step 4, update the matching logic in `useAgentChat.ts`. If the field is `toolCallId`, remove the `approvalCorrelationId` fallback. If there is NO correlation field, keep the fallback that matches the most-recent running exec ToolUse.

- [ ] **Step 7: Remove the dev-only console.log**

Revert the instrumentation added in Step 2.

- [ ] **Step 8: Commit**

Only commit if any code changed (Steps 5 or 6). Otherwise skip the commit.

```bash
git add -u
git commit -m "$(cat <<'EOF'
fix(approval): align event correlation with observed payload shape

Verified exec.approval.requested payload in dev; narrowed matching
logic (and/or added backend passthrough) to the field names actually
emitted by OpenClaw.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: End-to-end validation in browser (Chrome MCP)

**Files:** none modified. Execution validation only.

- [ ] **Step 1: Fresh dev session — Allow once path**

Run frontend dev (if not already running). Open browser on `dev.isol8.co/chat` and sign in. Ask agent: "Use exec with command=['whoami'] and host='node'". Verify:
  - An ApprovalCard appears inline under the assistant message.
  - Card shows `whoami` as primary line, `[node]` badge, cwd, agent name.
  - Click "Allow once". Button shows "Sending…" briefly.
  - Card collapses to `exec · allow-once` chip (or similar resolved chip).
  - Agent output shows the actual `whoami` output from the user's Mac (e.g. the user's macOS login name).

Expected: whoami output matches `$(whoami)` on the user's Mac.

- [ ] **Step 2: Trust path + persistence check**

Ask agent: "Use exec with command=['whoami', '-u'] and host='node'". New ApprovalCard appears. Click "Trust". Wait for resolved chip.

Then ask: "Use exec with command=['whoami'] and host='node'" again. Expected: no approval card — the command auto-approves because `/usr/bin/whoami` is now in the persisted allowlist.

Additional verification (optional, if AWS CLI is configured): ssh into the running ECS task and inspect `~/.openclaw/exec-approvals.json`:

```bash
TASK=$(aws ecs list-tasks --cluster isol8-dev-container-ClusterEB0386A7-Cjwm2mIlW4Aw \
  --service-name isol8-dev-service-ServiceD69D759B-Va1bdS6qTw9Y \
  --profile isol8-admin --region us-east-1 --query 'taskArns[0]' --output text | awk -F'/' '{print $NF}')
aws ecs execute-command --cluster isol8-dev-container-ClusterEB0386A7-Cjwm2mIlW4Aw \
  --task $TASK --container backend --interactive \
  --command "/bin/sh -c 'cat /mnt/efs/users/<user_id>/.openclaw/exec-approvals.json'" \
  --profile isol8-admin --region us-east-1
```

Expected: file contains an allowlist entry for `/usr/bin/whoami` with `source: "allow-always"`.

- [ ] **Step 3: Deny path**

Ask agent: "Use exec with command=['pwd'] and host='node'". ApprovalCard appears. Click "Deny". Expected:
  - Card collapses to red "exec · denied" chip.
  - Agent reports denial in chat (does not retry).

- [ ] **Step 4: Container-side (host=gateway) path**

Ask agent: "Use exec with command=['cat', '/etc/hostname']" (omit host — defaults to auto/gateway). ApprovalCard should appear with `[container]` badge. Click Allow once. Expected: agent reads container's hostname and returns it.

- [ ] **Step 5: Desktop app parity check**

Close browser. Launch `/Applications/Isol8.app`. Sign in. Repeat Step 1. Expected: identical behavior — ApprovalCard renders, decisions work.

- [ ] **Step 6: Document findings**

No code changes unless something fails. If a failure occurs, file it as a follow-up task (don't fix inline during E2E).

---

## Self-Review Checklist (author runs before handoff)

- [ ] Spec coverage: Every spec section maps to at least one task. (Scope=both hosts: Task 6 + Task 8 Step 4. Card info hierarchy: Task 3. Trust semantics: Task 3. Multiple pending: Tasks 5-6 inline-per-event rendering. RPC retry: Task 4. Architecture=ToolUse extension: Task 1. Audit chip: Task 6 `resolvedDecision` suffix.)
- [ ] No placeholders: search plan for "TBD", "TODO", "fix in follow-up" — none present.
- [ ] Type consistency: `ExecApprovalDecision`, `ApprovalRequest`, `ToolUse.status`, `onDecide` signature match across tasks 1/2/3/4/5/6.
- [ ] Commands are runnable: `pnpm tsc --noEmit`, `pnpm test --run <path>`, `pnpm test` — all valid per `apps/frontend/package.json`.
- [ ] TDD pattern: tasks with behavior changes (2, 3, 4, 6) start with failing test → verify fail → implement → verify pass → commit.

---

## Execution Handoff

Plan saved to `docs/superpowers/plans/2026-04-18-exec-approval-card.md`. Two execution options:

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
