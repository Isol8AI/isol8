# Exec Approval Card — Design

**Status:** Approved
**Author:** Prasiddha (with Claude)
**Date:** 2026-04-18

## Problem

When an Isol8 agent runs a shell command that isn't in its allowlist, OpenClaw blocks it and surfaces a `/approve <id> <decision>` chat message. This UX is terrible: the user has to type a slash command with an opaque ID to unblock their agent. It fails even more badly on the new desktop app, where `host=node` routes commands to the user's local Mac — the user should clearly see what's about to run on their machine before it does.

This spec replaces the text-based approval path with an inline Claude Code–style card in chat: three buttons (Allow once / Trust / Deny), rendered wherever the assistant is running a tool.

## Goals

1. One approval UX shared across both the web app (`dev.isol8.co`) and the Tauri desktop app, without any desktop-specific code.
2. Cover both `host=gateway` (commands in the container) and `host=node` (commands on the user's Mac).
3. Preserve approval decisions in chat history as audit evidence.
4. Be honest about trust scope — the card must accurately convey what "Trust" persists, so users don't over-grant.
5. Server (OpenClaw) remains the source of truth for approval state and persistence. Frontend does not re-implement allowlist logic.

## Non-goals

- Approvals for non-exec tools (web.fetch, file writes, etc.). Only `exec.approval.requested` in this iteration.
- A native macOS system dialog. In-chat card only.
- A dedicated "Pending approvals" sidebar pane. Cards live inline with chat.
- Per-argv argPattern trust on macOS. OpenClaw only builds argPatterns on Windows (`exec-approvals-allowlist.ts:909-912`), so offering "trust with these exact args" on macOS would be a lie.
- Denial with a reason field. Deny is a single click; if the user wants to tell the agent something, they do it in the next chat message.
- Changes to the `system.execApprovals.get/set` node-side RPCs. They remain read-only snapshots (per OpenClaw source at `bash-tools.exec-host-node.ts:59-100`, node-side does not re-check approvals; the container gates before forwarding).

## Design

### Approach

The approval is modeled as a new state in the existing `ToolUse` lifecycle, not as a new message kind or a separate overlay. A ToolUse's `status` gains two new values (`"pending-approval"`, `"denied"`) and a new optional `pendingApproval` field holding the approval request metadata. The existing `ToolPill` component in `MessageList.tsx` gets a new render branch for these states.

This keeps one mental model (everything a tool does is a ToolUse), reuses the inline placement and ordering machinery, and makes the collapse-to-audit-chip behavior fall out naturally from rendering the same ToolPill in a terminal state.

### Data flow

**Incoming (event → UI):**

```
OpenClaw (container)
  │ emits exec.approval.requested {id, request, createdAtMs, expiresAtMs}
  │ (openclaw/src/gateway/server-methods/exec-approval.ts:269-274)
  ▼
Isol8 backend connection_pool (apps/backend/core/gateway/connection_pool.py)
  │ forwards via Management API to frontend WS
  ▼
Frontend useGateway.handleMessage → eventHandlersRef
  │ (apps/frontend/src/hooks/useGateway.tsx:188-191)
  ▼
useAgentChat subscribes via onEvent("exec.approval.requested")
  │ attaches pendingApproval to the in-flight ToolUse (matched by toolCallId/
  │ correlation field — exact field name TBV empirically; if no match, create
  │ a standalone ToolUse with status="pending-approval")
  ▼
MessageList re-renders → ToolPill renders ApprovalCard inline
```

**Outgoing (decision → persistence):**

```
User clicks a button in ApprovalCard
  │ local spinner state on clicked button
  ▼
sendReq("exec.approval.resolve", {id, decision})
  │ (useGateway.tsx:357-401)
  │ decision ∈ {"allow-once" | "allow-always" | "deny"}
  ▼
Backend websocket_chat.py (existing RPC proxy path, same as agents.list)
  │ forwards to container's gateway
  ▼
OpenClaw exec-approval.ts:333 handler
  │ validates decision ∈ snapshot.request.allowedDecisions
  │ if allow-always: persistAllowAlwaysPatterns writes to
  │   ~/.openclaw/exec-approvals.json as {pattern: resolvedPath,
  │   argPattern: undefined on macOS, source: "allow-always"}
  │ emits exec.approval.resolved event
  │ unblocks pending exec
  ▼
Tool runs (or denies) → tool_end / tool_error returns via normal path
  ▼
ToolUse status updated to "done" / "error" / "denied"
  ▼
ApprovalCard collapses to chip: "✓ Allowed whoami" or "✗ Denied whoami"
```

### Components

**Frontend** (under `apps/frontend/src/`):

| Component | Path | Change |
|---|---|---|
| `ToolUse` type | `components/chat/MessageList.tsx:36-43` | Add `"pending-approval"` and `"denied"` to `status`; add optional `pendingApproval?: ApprovalRequest` field |
| `ApprovalRequest` type | New, co-located with ToolUse | `{id, command, commandArgv?, host, cwd?, resolvedPath?, agentId, allowedDecisions, expiresAtMs}` |
| `ApprovalCard` | `components/chat/ApprovalCard.tsx` (new) | Renders command as primary line, host badge, cwd, agent name, "Details" expander (resolvedPath, argv, sessionKey), and 3 buttons built on shadcn `Button`. Disables any button whose decision isn't in `allowedDecisions`. |
| `ToolPill` render branch | `components/chat/MessageList.tsx:194-251` | Route `status === "pending-approval"` to `<ApprovalCard>`; `status === "denied"` to a chip `✗ Denied {command}` |
| `useAgentChat` | `hooks/useAgentChat.ts:230-392` | Subscribe to `exec.approval.requested` via `useGateway.onEvent`; handler mutates matching ToolUse. Also subscribe to `exec.approval.resolved` for external resolutions. Expose `resolveApproval(id, decision)` from the hook for ApprovalCard to call. |

**Backend** (conditional):

| File | Change |
|---|---|
| `apps/backend/core/gateway/connection_pool.py` | If `exec.approval.requested` arrives wrapped in the agent-event stream, add a passthrough case to `_transform_agent_event` that re-emits it verbatim. Expected no-op — this event is a top-level gateway event, not part of the agent stream. Verify empirically. |
| `apps/backend/routers/node_proxy.py` | Same passthrough check for node-routed approvals. Expected no-op. |

**Tauri desktop:** no changes.

### Card layout

Default view (Claude Code–style):

```
┌─────────────────────────────────────────────────────────┐
│ whoami                                      [node] [⏵]  │
│ /Users/prasiddha                                        │
│ main (qwen3-vl-235b)                                    │
│                                                         │
│ [ Allow once ]  [ Trust ]  [ Deny ]                     │
└─────────────────────────────────────────────────────────┘
```

Expanded (Details toggle):

```
┌─────────────────────────────────────────────────────────┐
│ whoami                                      [node] [⏷]  │
│ /Users/prasiddha                                        │
│ main (qwen3-vl-235b)                                    │
│                                                         │
│ Resolves to  /usr/bin/whoami                            │
│ argv         ["whoami"]                                 │
│ Session      personal.user_3CV....main                  │
│                                                         │
│ [ Allow once ]  [ Trust ]  [ Deny ]                     │
│                                                         │
│ Trust will always allow /usr/bin/whoami on this Mac     │
│ (any arguments).                                        │
└─────────────────────────────────────────────────────────┘
```

Collapsed after decision (chip):

```
✓ Allowed whoami · allow-once          (or: allow-always / denied)
```

For shell wrappers (`bash -lc 'whoami'`), the primary line shows the inner command (`whoami`), the Details expander shows the raw wrapper (`bash -lc 'whoami'`), and the Trust copy reflects what OpenClaw actually persists (the inner command's resolvedPath, `/usr/bin/whoami`). This matches OpenClaw's server-side unwrapping behavior at `exec-approvals-allowlist.ts:965-985`.

### Matching events to ToolUses

The event payload carries `id`, `request.agentId`, and likely a correlation field that ties to the originating tool call (exact field name to be confirmed empirically during implementation — may be `toolCallId`, `approvalCorrelationId`, or inferable from timing + agentId + sessionKey).

Matching strategy:
1. If a ToolUse exists in the current message with a matching correlation field and `status === "running"`, mutate it to `"pending-approval"` and attach `pendingApproval`.
2. If no match exists, create a new ToolUse with status `"pending-approval"`, `tool: "exec"`, and attach `pendingApproval`. When the later `tool_start` arrives for the same correlation, merge (don't create a duplicate).
3. If a `pendingApproval.id` collision is detected (duplicate `exec.approval.requested`), overwrite — treat as idempotent.

### State transitions

```
ToolUse.status:
  running ─► pending-approval ─► running (allow-once / allow-always)
                              └► denied  (deny)
  running ─► done | error                (no approval needed, allowlisted)
  pending-approval ─► denied             (server-side expiry → resolved event with decision="deny")
```

## Edge cases (documented, not all actively coded)

1. **RPC fails on decision click** — button shows spinner → inline error "Couldn't send decision. Retry". Actively coded.
2. **Server rejects decision** (e.g., clicked Trust when `allowedDecisions === ["allow-once"]`) — surface the server's error message inline; disable the rejected button. Actively coded.
3. **Event arrives without matching ToolUse** — create a standalone ToolUse (see Matching above). Actively coded.
4. **Duplicate `exec.approval.requested`** — idempotent overwrite.
5. **`exec.approval.resolved` for unknown id** — no-op with debug log.
6. **`exec.approval.resolved` arrives while card is open** (external decision, server timeout) — card collapses to chip with server's outcome; any in-flight client RPC is abandoned.
7. **Malformed event payload** — log + drop. Never throw in render.
8. **User navigates away with pending approval** — nothing client-side. Server 30-min timeout kicks in.
9. **WebSocket reconnect mid-approval** — rely on history replay; if pending approvals don't survive history, the user re-triggers. Not actively coded.

## Testing

**Unit (Vitest):**
- `ApprovalCard.test.tsx` — button rendering across `allowedDecisions` subsets; expander toggle; spinner state during RPC.
- `useAgentChat.test.ts` — `exec.approval.requested` creates/mutates ToolUse; `exec.approval.resolved` collapses it; decision click calls `sendReq` with correct shape.

**E2E (Chrome MCP, driven manually):**
- Trigger an agent to run `whoami` on `host=node` → approval card appears → click "Allow once" → command returns my Mac's username → card collapses to `✓ Allowed whoami · allow-once`.
- Same flow with "Trust" → confirm `~/.openclaw/exec-approvals.json` in EFS has a new entry for `/usr/bin/whoami`. Re-trigger the same command → auto-approves without a card.
- Same flow with "Deny" → agent reports denial → card shows `✗ Denied whoami`.
- One test against `host=gateway` with a container-side command to confirm the UI is uniform.

## Rollout

- Ship behind the existing chat UI — no feature flag needed. The new ToolUse states are additive; messages from before this change still render correctly (they only use `"running"` / `"done"` / `"error"`).
- Deploy web + desktop simultaneously. Desktop picks it up on next webview reload.

## Open questions (resolve during implementation)

- Exact correlation field in `exec.approval.requested` payload for matching to a ToolUse — determine by logging a live event.
- Whether `connection_pool.py` needs a passthrough case for this event or if it's already top-level — verify with the same live event.
- Whether the Isol8 backend's RPC proxy at `websocket_chat.py` handles `exec.approval.resolve` out of the box (as it does for `agents.list`) or needs explicit routing.
