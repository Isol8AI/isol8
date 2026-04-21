// frontend/src/hooks/useAgentChat.ts
/**
 * Agent chat hook that uses the shared GatewayProvider WebSocket.
 *
 * Message protocol (unchanged):
 * - Send: { type: "agent_chat", agent_id: string, message: string }
 * - Receive: { type: "chunk", content: string }
 * - Receive: { type: "done" }
 * - Receive: { type: "error", message: string }
 * - Receive: { type: "heartbeat" }
 */

"use client";

import * as React from "react";
import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import posthog from "posthog-js";
import {
  useGateway,
  type ChatIncomingMessage,
  type BudgetExceededPayload,
} from "@/hooks/useGateway";
import type {
  ApprovalRequest,
  ExecApprovalDecision,
  ToolUse,
} from "@/components/chat/MessageList";

// =============================================================================
// Debug instrumentation
//
// Temporary. Wired to diagnose the "one-turn-behind after tool approval" bug —
// where isStreaming appears to flip to false at the click of an approval
// decision, and the subsequent post-approval stream lands in the NEXT
// user-message bubble.
//
// OFF BY DEFAULT IN PRODUCTION. User opts in per-browser via devtools:
//   localStorage.setItem("chat_debug", "1")   // then reload
//   localStorage.removeItem("chat_debug")     // to disable
//
// When enabled, emits to console.debug (live devtools inspection) AND
// posthog ("chat_debug" event, persistent queryable timeline). Chunk /
// heartbeat events are excluded from posthog to keep volume down.
//
// Payload scrubbing: never include raw user messages, assistant content,
// or command args. Only log shape/metadata — lengths, counts, type tags,
// boolean flags, identifiers.
//
// Rip this out once the bug is identified.
// =============================================================================
function isChatDebugEnabled(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem("chat_debug") === "1";
  } catch {
    return false;
  }
}
function chatDebug(event: string, payload: Record<string, unknown> = {}) {
  if (!isChatDebugEnabled()) return;
  // Using console.log rather than console.debug so entries show up at
  // the Chrome default log level (debug is a Verbose-only level, hidden
  // by default and a common source of "I see nothing in the console"
  // confusion).
  // eslint-disable-next-line no-console
  console.log("[chat-debug]", event, { ts: Date.now(), ...payload });
  try {
    posthog?.capture?.("chat_debug", { event, ...payload });
  } catch {
    // posthog not initialized (local dev without key) — ignore.
  }
}

// Re-export ToolUse so existing consumers (AgentChatWindow) keep working
// after this hook switched to the canonical MessageList definition.
export type { ToolUse } from "@/components/chat/MessageList";

// =============================================================================
// Friendly error messages
// =============================================================================

const ERROR_PATTERNS: [RegExp, string][] = [
  [/timed out during opening handshake/i, "Your agent is starting up — please try again in a moment."],
  [/Gateway not healthy/i, "Your agent is not ready yet. Please try again in a moment."],
  [/health check timed out/i, "Your agent is not responding. Please try again in a moment."],
  [/Gateway connection lost/i, "Lost connection to your agent. Retrying..."],
  [/Connection closed/i, "Connection to your agent was interrupted. Please try again."],
  [/session file locked/i, "Your agent is busy with another request. Please wait a moment and try again."],
  [/Model access is denied/i, "This model is not available. Try switching to a different model in settings."],
  [/Agent run failed/i, "Your agent encountered an error. Please try again."],
];

function friendlyError(raw: string): string {
  for (const [pattern, friendly] of ERROR_PATTERNS) {
    if (pattern.test(raw)) return friendly;
  }
  return raw;
}

// =============================================================================
// Content extraction
// =============================================================================

/**
 * Extract text from OpenClaw message content blocks.
 * chat.history returns content as an array of blocks: [{ type: "text", text: "..." }, ...]
 */
interface ContentBlock {
  type: string;
  text?: string;
  thinking?: string;
}

function extractTextContent(content: ContentBlock[]): string {
  return content
    .filter((block) => block.type === "text" || block.type === "output_text" || block.type === "input_text")
    .map((block) => block.text ?? "")
    .join("");
}

function extractThinkingContent(content: ContentBlock[]): string {
  return content
    .filter((block) => block.type === "thinking")
    .map((block) => block.thinking ?? block.text ?? "")
    .join("\n\n");
}

// =============================================================================
// Types
// =============================================================================

export interface AgentMessage {
  role: "user" | "assistant";
  content: string;
  thinking?: string;
  toolUses?: ToolUse[];
}

export const BOOTSTRAP_MESSAGE =
  "Hello! Please run Bootstrap.md — I'd love to learn about everyday life use cases where you can be helpful and automate work for me.";

export interface UseAgentChatReturn {
  messages: AgentMessage[];
  isStreaming: boolean;
  error: string | null;
  budgetError: BudgetExceededPayload | null;
  sendMessage: (message: string) => Promise<void>;
  cancelMessage: () => Promise<void>;
  clearMessages: () => void;
  isConnected: boolean;
  isLoadingHistory: boolean;
  needsBootstrap: boolean;
  resolveApproval: (id: string, decision: ExecApprovalDecision) => Promise<void>;
}

interface InternalMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  thinking?: string;
  toolUses?: ToolUse[];
}

// =============================================================================
// Module-level message cache
//
// Survives component unmounts (navigation away from /chat and back) but
// clears on full page refresh. Keyed by agentId so each agent's history
// is preserved independently.
// =============================================================================

const _messageCache = new Map<string, InternalMessage[]>();
const _needsBootstrap = new Set<string>();

// =============================================================================
// Hook
//
// NOTE: Only one useAgentChat instance should be active at a time. The backend
// protocol does not tag chunk/done/error messages with an agent_id, so
// concurrent instances would receive each other's messages. The UI enforces
// this by rendering a single AgentChatWindow.
// =============================================================================

export function useAgentChat(agentId: string | null, sessionName: string): UseAgentChatReturn {
  const { isConnected, sendChat, onChatMessage, onEvent, sendReq } = useGateway();

  // Cache key includes session name so org members don't share history cache
  const cacheKey = agentId ? `${agentId}:${sessionName}` : null;

  const [messages, setMessages] = useState<InternalMessage[]>(
    () => (cacheKey ? _messageCache.get(cacheKey) ?? [] : []),
  );
  const [isStreaming, _setIsStreamingRaw] = useState(false);
  // Debug wrapper: every streaming-flag flip is logged with source. Removing
  // this wrapper once the post-approval bug is diagnosed.
  const isStreamingRef = useRef(false);
  const setIsStreaming = useCallback((value: boolean, source?: string) => {
    const prev = isStreamingRef.current;
    isStreamingRef.current = value;
    chatDebug("setIsStreaming", { from: prev, to: value, source: source ?? "unknown" });
    _setIsStreamingRaw(value);
  }, []);
  const [error, setError] = useState<string | null>(null);
  const [budgetError, setBudgetError] = useState<BudgetExceededPayload | null>(null);
  const [historyLoadState, setHistoryLoadState] = useState<"idle" | "loading" | "done">("idle");
  const isLoadingHistory = historyLoadState === "loading";

  // Multi-bubble: one assistant message per OpenClaw runId. OpenClaw assigns
  // a new runId per LLM turn within a single chat.send; each turn gets its
  // own bubble.
  // See docs/superpowers/specs/2026-04-21-multi-bubble-chat-design.md.
  type RunState = {
    messageId: string;
    streamContent: string;
    thinking: string;
  };
  const runsRef = useRef<Map<string, RunState>>(new Map());

  // Tracks runIds that have been finalized (done / error / budget / cancel /
  // clear / agent-drop). Any late chunk/thinking/tool_start event arriving for
  // one of these runIds is silently dropped by getOrCreateBubble — without
  // this, such a late event would create a brand-new empty assistant bubble
  // and flip isStreaming back to true (ghost-bubble regression, M1).
  //
  // Bounded to ~100 entries via FIFO eviction below; the first-inserted runId
  // is evicted when the set would otherwise grow past the cap. This avoids
  // unbounded growth over long sessions while still covering the protocol's
  // realistic out-of-order window (events straggle within a single turn, not
  // across dozens of turns).
  const finalizedRunsRef = useRef<Set<string>>(new Set());

  const getOrCreateBubble = useCallback((runId: string): string | null => {
    // Late event for an already-finalized run — drop silently. This
    // replicates the old `if (!currentAssistantIdRef.current) return;`
    // blanket guard, but scoped to truly-finalized runs instead of the
    // global streaming flag.
    if (finalizedRunsRef.current.has(runId)) {
      return null;
    }

    const existing = runsRef.current.get(runId);
    if (existing) return existing.messageId;

    const messageId = `assistant-${crypto.randomUUID()}`;
    runsRef.current.set(runId, { messageId, streamContent: "", thinking: "" });
    setMessages((prev) => [
      ...prev,
      { id: messageId, role: "assistant", content: "" },
    ]);
    if (!isStreamingRef.current) {
      setIsStreaming(true, `run-${runId.slice(0, 12)}-start`);
    }
    return messageId;
  }, [setIsStreaming]);

  const finalizeBubble = useCallback((runId: string) => {
    runsRef.current.delete(runId);
    finalizedRunsRef.current.add(runId);
    // Bounded LRU-ish: cap size to avoid unbounded growth on long sessions.
    // Set iteration order is insertion order, so values().next() gives the
    // oldest entry.
    if (finalizedRunsRef.current.size > 100) {
      const first = finalizedRunsRef.current.values().next().value;
      if (first) finalizedRunsRef.current.delete(first);
    }
    if (runsRef.current.size === 0) {
      setIsStreaming(false, `run-${runId.slice(0, 12)}-done`);
    }
  }, [setIsStreaming]);

  // Mark every currently-active run as finalized, then clear runsRef. Used by
  // cancel / clear / global-error branches: wiping runsRef without also
  // populating finalizedRunsRef would let a late in-flight chunk/thinking/
  // tool_start event slip past getOrCreateBubble (it wouldn't find the runId
  // in either ref) and spawn a ghost assistant bubble that re-enables
  // isStreaming — silently undoing the cancel/clear. Never clear
  // finalizedRunsRef for the same reason; rely on the 100-entry FIFO cap in
  // finalizeBubble to bound growth.
  const finalizeAllActiveRuns = useCallback(() => {
    for (const runId of runsRef.current.keys()) {
      finalizedRunsRef.current.add(runId);
      if (finalizedRunsRef.current.size > 100) {
        const first = finalizedRunsRef.current.values().next().value;
        if (first) finalizedRunsRef.current.delete(first);
      }
    }
    runsRef.current.clear();
  }, []);

  const agentIdRef = useRef(agentId);
  useEffect(() => {
    agentIdRef.current = agentId;
  }, [agentId]);

  // ---- Sync messages to module-level cache ----
  useEffect(() => {
    if (cacheKey && messages.length > 0) {
      _messageCache.set(cacheKey, messages);
    }
  }, [cacheKey, messages]);

  // ---- Fetch history on mount / agent change ----
  const historyLoadedRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (!agentId || !cacheKey || !isConnected) return;
    if (historyLoadedRef.current.has(cacheKey)) return;
    // Don't fetch if we already have cached messages
    if (_messageCache.has(cacheKey)) {
      historyLoadedRef.current.add(cacheKey);
      return;
    }

    // Session key must match the backend's convention (websocket_chat.py:588):
    // all users get agent:{agentId}:{userId} to isolate from cron/system activity
    const sessionKey = `agent:${agentId}:${sessionName}`;

    // Use Promise.resolve to move setState into a callback (satisfies react-hooks/set-state-in-effect)
    Promise.resolve().then(() => setHistoryLoadState("loading"));

    sendReq("chat.history", { sessionKey, limit: 200 })
      .then((result: unknown) => {
        const historyResult = result as {
          messages?: Array<{ role: string; content: Array<{ type: string; text?: string }> }>;
        };
        historyLoadedRef.current.add(cacheKey);
        setHistoryLoadState("done");

        if (!historyResult?.messages?.length) {
          // No history = first time. Flag for bootstrap suggestion in chat input.
          _needsBootstrap.add(cacheKey);
          return;
        }

        if (agentIdRef.current !== agentId) return; // agent changed during fetch

        const loaded: InternalMessage[] = historyResult.messages
          .filter((m: { role: string }) => m.role === "user" || m.role === "assistant")
          .map((m: { role: string; content: ContentBlock[] }, i: number) => {
            const thinking = extractThinkingContent(m.content);
            return {
              id: `history-${i}`,
              role: m.role as "user" | "assistant",
              content: extractTextContent(m.content),
              ...(thinking ? { thinking } : {}),
            };
          })
          .filter((m) => m.content.length > 0);

        if (loaded.length > 0) {
          setMessages(loaded);
          _messageCache.set(cacheKey, loaded);
        }
      })
      .catch((err: unknown) => {
        console.warn("Failed to fetch chat history:", err);
        historyLoadedRef.current.add(cacheKey);
        setHistoryLoadState("done");
      });
  }, [agentId, cacheKey, sessionName, isConnected, sendReq]);

  // ---- Chat message handler ----
  // Dependencies are intentionally minimal ([onChatMessage]) because all
  // mutable values are accessed through refs, avoiding stale closures.

  useEffect(() => {
    return onChatMessage((msg: ChatIncomingMessage) => {
      // Debug: log every non-chunk message at arrival, plus chunk metadata
      // (not content — chunks fire per-token and would spam posthog).
      if (msg.type !== "chunk" && msg.type !== "heartbeat") {
        chatDebug("chat_msg_rx", {
          msg_type: msg.type,
          msg_agent_id: (msg as { agent_id?: string }).agent_id,
          my_agent_id: agentIdRef.current,
          run_count: runsRef.current.size,
          streaming: isStreamingRef.current,
          error_code: (msg as { code?: string }).code,
          // NOTE: deliberately do not include the error message string — it
          // can carry user-provided content (budget/tier labels, partial
          // agent output on aborted runs).
          has_error_message: Boolean((msg as { message?: string }).message),
        });
      }

      // Chunk arrival tracer (console-only — NEVER posthog, NEVER content).
      // We need to know WHEN chunks arrive relative to approval events to
      // decide whether the post-approval chunk-routing bug is a same-bubble
      // or cross-bubble misrouting. Logs length only (shape, not content).
      // Skips posthog entirely to avoid per-token volume.
      if (msg.type === "chunk" && isChatDebugEnabled()) {
        // eslint-disable-next-line no-console
        console.log("[chat-debug]", "chunk_rx", {
          ts: Date.now(),
          content_length: msg.content?.length ?? 0,
          msg_agent_id: msg.agent_id,
          my_agent_id: agentIdRef.current,
          run_count: runsRef.current.size,
          streaming: isStreamingRef.current,
        });
      }

      // Drop messages meant for a different agent. Heartbeat and
      // update_available aren't tied to a specific run. Errors are
      // allowed through even without agent_id as a safety valve —
      // some failure paths (client-side validation, etc.) have no
      // agent context but still need to clear the streaming state.
      const isUntaggedBroadcast =
        msg.type === "heartbeat" || msg.type === "update_available";
      const isUntaggedError = msg.type === "error" && msg.agent_id === undefined;
      if (!isUntaggedBroadcast && !isUntaggedError && msg.agent_id !== agentIdRef.current) {
        // TS has narrowed out "heartbeat"/"chunk" by this point via the
        // isUntaggedBroadcast aliased condition; log unconditionally.
        chatDebug("chat_msg_dropped_agent_mismatch", {
          msg_type: (msg as { type: string }).type,
          msg_agent_id: (msg as { agent_id?: string }).agent_id,
          my_agent_id: agentIdRef.current,
        });
        return;
      }

      if (msg.type === "chunk") {
        const runId = msg.runId;
        const messageId = getOrCreateBubble(runId);
        // Late event for a finalized run — drop.
        if (!messageId) return;
        const run = runsRef.current.get(runId)!;
        run.streamContent = msg.content;
        const updatedContent = run.streamContent;
        setMessages((prev) =>
          prev.map((m) =>
            m.id === messageId ? { ...m, content: updatedContent } : m,
          ),
        );
        return;
      }

      if (msg.type === "done") {
        const runId = msg.runId;
        finalizeBubble(runId);
        return;
      }

      if (msg.type === "error") {
        // Budget-exceeded is a global terminal — not tied to a specific run.
        if (msg.code === "BUDGET_EXCEEDED") {
          setBudgetError({
            code: "BUDGET_EXCEEDED",
            current_spend: msg.current_spend ?? 0,
            included_budget: msg.included_budget ?? 0,
            within_included: msg.within_included ?? false,
            overage_available: msg.overage_available ?? false,
            overage_enabled: msg.overage_enabled ?? false,
            is_subscribed: msg.is_subscribed ?? false,
            tier: msg.tier ?? "free",
          });
          // Remove any empty assistant placeholders across active runs.
          const activeMessageIds = new Set(
            Array.from(runsRef.current.values()).map((r) => r.messageId),
          );
          setMessages((prev) => prev.filter((m) => !activeMessageIds.has(m.id)));
          finalizeAllActiveRuns();
          setIsStreaming(false, "error-budget");
          return;
        }

        const displayError = friendlyError(msg.message);

        if (msg.runId) {
          // Scoped error: finalize that bubble only. Other runs continue.
          const run = runsRef.current.get(msg.runId);
          if (run) {
            const messageId = run.messageId;
            setMessages((prev) =>
              prev.map((m) =>
                m.id === messageId ? { ...m, content: `Error: ${displayError}` } : m,
              ),
            );
            finalizeBubble(msg.runId);
          } else {
            // Unknown runId: the error fired before any chunk/thinking/
            // tool_start arrived, so no bubble exists yet. Append a visible
            // error-marked assistant message so the user sees the failure
            // (same UX as the sendMessage catch branch below), and clear
            // the streaming flag if no other runs are active — otherwise
            // sendMessage's early setIsStreaming(true) leaves the input
            // stuck in "Stop" mode (Codex P1 / S3).
            const errMsgId = `assistant-${crypto.randomUUID()}`;
            setMessages((prev) => [
              ...prev,
              { id: errMsgId, role: "assistant", content: `Error: ${displayError}` },
            ]);
            // Remember this runId as finalized so any late straggler events
            // for it don't create a ghost bubble.
            finalizedRunsRef.current.add(msg.runId);
            if (finalizedRunsRef.current.size > 100) {
              const first = finalizedRunsRef.current.values().next().value;
              if (first) finalizedRunsRef.current.delete(first);
            }
            if (runsRef.current.size === 0) {
              setIsStreaming(false, "error-scoped-unknown-run");
            }
          }
          setError(displayError);
          return;
        }

        // Global error (no runId): mark every active bubble and clear state.
        const activeMessageIds = new Set(
          Array.from(runsRef.current.values()).map((r) => r.messageId),
        );
        setMessages((prev) =>
          prev.map((m) =>
            activeMessageIds.has(m.id)
              ? { ...m, content: `Error: ${displayError}` }
              : m,
          ),
        );
        setError(displayError);
        finalizeAllActiveRuns();
        setIsStreaming(false, "error-generic");
        return;
      }

      if (msg.type === "thinking") {
        const runId = msg.runId;
        const messageId = getOrCreateBubble(runId);
        // Late event for a finalized run — drop.
        if (!messageId) return;
        const run = runsRef.current.get(runId)!;
        run.thinking = msg.content;
        const updatedThinking = run.thinking;
        setMessages((prev) =>
          prev.map((m) =>
            m.id === messageId ? { ...m, thinking: updatedThinking } : m,
          ),
        );
        return;
      }

      if (msg.type === "tool_start") {
        const runId = msg.runId;
        const messageId = getOrCreateBubble(runId);
        // Late event for a finalized run — drop.
        if (!messageId) return;
        setMessages((prev) =>
          prev.map((m) => {
            if (m.id !== messageId) return m;
            const existing = m.toolUses ?? [];
            const existingIdx =
              msg.toolCallId !== undefined
                ? existing.findIndex((t) => t.toolCallId === msg.toolCallId)
                : -1;
            if (existingIdx >= 0) {
              const next = existing.slice();
              const prior = next[existingIdx];
              next[existingIdx] = {
                ...prior,
                tool: msg.tool,
                status: prior.status ?? ("running" as const),
                ...(msg.args ? { args: msg.args } : {}),
              };
              return { ...m, toolUses: next };
            }
            return {
              ...m,
              toolUses: [
                ...existing,
                {
                  tool: msg.tool,
                  toolCallId: msg.toolCallId,
                  status: "running" as const,
                  ...(msg.args ? { args: msg.args } : {}),
                },
              ],
            };
          }),
        );
        return;
      }

      if (msg.type === "tool_end" || msg.type === "tool_error") {
        const runId = msg.runId;
        const run = runsRef.current.get(runId);
        const messageId = run?.messageId;
        const nextStatus = msg.type === "tool_end" ? "done" : "error";

        if (!messageId) {
          // No active run for this runId — the bubble was already finalized
          // (late tool_end after chat.final, or error-scoped-unknown-run).
          // Fall back to a toolCallId scan across all assistant messages so
          // the toolCall doesn't stay stuck at status "running" forever (S2).
          if (msg.toolCallId !== undefined) {
            const targetCallId = msg.toolCallId;
            setMessages((prev) => {
              let matched = false;
              const next = prev.map((m) => {
                if (m.role !== "assistant") return m;
                const toolUses = m.toolUses ?? [];
                const idx = toolUses.findIndex(
                  (t) => t.toolCallId === targetCallId && t.status === "running",
                );
                if (idx < 0) return m;
                matched = true;
                const updated = toolUses.slice();
                updated[idx] = {
                  ...updated[idx],
                  status: nextStatus as "done" | "error",
                  ...(msg.result ? { result: msg.result } : {}),
                  ...(msg.meta ? { meta: msg.meta } : {}),
                };
                return { ...m, toolUses: updated };
              });
              return matched ? next : prev;
            });
          }
          // If no toolCallId or no match, silently drop (same as before).
          return;
        }
        setMessages((prev) =>
          prev.map((m) => {
            if (m.id !== messageId) return m;
            const toolUses = (m.toolUses || []).map((t) => {
              const matchesCallId =
                msg.toolCallId !== undefined &&
                t.toolCallId === msg.toolCallId;
              const matchesName =
                msg.toolCallId === undefined && t.tool === msg.tool;
              const isRunning = t.status === "running";
              if (isRunning && (matchesCallId || matchesName)) {
                return {
                  ...t,
                  status: nextStatus as "done" | "error",
                  ...(msg.result ? { result: msg.result } : {}),
                  ...(msg.meta ? { meta: msg.meta } : {}),
                };
              }
              return t;
            });
            return { ...m, toolUses };
          }),
        );
        return;
      }

      if (msg.type === "heartbeat") {
        // If any run has empty content so far, show a "working..." hint on
        // its bubble. Picks the first empty run (usually there's only one).
        for (const run of runsRef.current.values()) {
          if (!run.streamContent) {
            const messageId = run.messageId;
            setMessages((prev) =>
              prev.map((m) =>
                m.id === messageId && !m.content
                  ? { ...m, content: "Agent is working..." }
                  : m,
              ),
            );
            break;
          }
        }
      }
    });
  }, [onChatMessage]);

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
      chatDebug("approval_requested_event_rx", {
        id: payload?.id,
        host: payload?.request?.host,
        // shape only — no raw command (may contain paths/args)
        has_command: Boolean(payload?.request?.command),
        run_count: runsRef.current.size,
        streaming: isStreamingRef.current,
      });
      if (!payload?.id || !payload.request?.command) return;

      // Scope to this chat's agent. The backend forwards non-agent/chat events
      // as generic events (see connection_pool.py), so a parallel tab or
      // another agent's session for the same user would otherwise inject a
      // foreign approval card here and let the user resolve the wrong id.
      const eventAgentId = payload.request.agentId;
      if (eventAgentId && eventAgentId !== agentIdRef.current) return;

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

      setMessages((prev) => {
        // Idempotent: a retry/reconnect can redeliver the same approval.
        // First pass: find any existing bubble that already has this approval
        // id (dedupe).
        for (const m of prev) {
          if (m.role !== "assistant") continue;
          const idx = (m.toolUses ?? []).findIndex(
            (t) => t.pendingApproval?.id === req.id,
          );
          if (idx >= 0) {
            return prev.map((row) => {
              if (row.id !== m.id) return row;
              const next = (row.toolUses ?? []).slice();
              next[idx] = {
                ...next[idx],
                status: "pending-approval",
                pendingApproval: req,
              };
              return { ...row, toolUses: next };
            });
          }
        }

        // Second pass: find the target tool use by correlation id across
        // all assistant messages. Prefer exact toolCallId match; for
        // correlationless events, bind to the NEWEST running exec.
        if (correlation) {
          for (const m of prev) {
            if (m.role !== "assistant") continue;
            const idx = (m.toolUses ?? []).findIndex(
              (t) => t.toolCallId === correlation,
            );
            if (idx >= 0) {
              return prev.map((row) => {
                if (row.id !== m.id) return row;
                const next = (row.toolUses ?? []).slice();
                next[idx] = {
                  ...next[idx],
                  status: "pending-approval",
                  pendingApproval: req,
                };
                return { ...row, toolUses: next };
              });
            }
          }
        } else {
          // Scan from newest message backwards for a running exec.
          for (let i = prev.length - 1; i >= 0; i--) {
            const m = prev[i];
            if (m.role !== "assistant") continue;
            const toolUses = m.toolUses ?? [];
            for (let j = toolUses.length - 1; j >= 0; j--) {
              if (toolUses[j].tool === "exec" && toolUses[j].status === "running") {
                return prev.map((row, rowIdx) => {
                  if (rowIdx !== i) return row;
                  const next = toolUses.slice();
                  next[j] = {
                    ...next[j],
                    status: "pending-approval",
                    pendingApproval: req,
                  };
                  return { ...row, toolUses: next };
                });
              }
            }
          }
        }

        // Nothing matched — attach to the newest assistant message as a new
        // tool entry (preserves old behavior for correlationless cases
        // where no tool has started yet).
        // Protocol invariant: OpenClaw emits `tool_start` (which creates the
        // bubble and the toolCall entry) before `exec.approval.requested` for
        // that toolCall, so at least one assistant bubble exists by the time
        // we get here. The `lastAssistantIdx < 0` guard is a safety net for
        // protocol violations, not a normal code path.
        const lastAssistantIdx = (() => {
          for (let i = prev.length - 1; i >= 0; i--) {
            if (prev[i].role === "assistant") return i;
          }
          return -1;
        })();
        if (lastAssistantIdx < 0) return prev;
        return prev.map((row, i) => {
          if (i !== lastAssistantIdx) return row;
          return {
            ...row,
            toolUses: [
              ...(row.toolUses ?? []),
              {
                tool: "exec",
                toolCallId: correlation,
                status: "pending-approval",
                pendingApproval: req,
              },
            ],
          };
        });
      });
    });

    const unsubResolved = onEvent((eventName, data) => {
      if (eventName !== "exec.approval.resolved") return;
      const payload = data as { id?: string; decision?: ExecApprovalDecision };
      chatDebug("approval_resolved_event_rx", {
        id: payload?.id,
        decision: payload?.decision,
        run_count: runsRef.current.size,
        streaming: isStreamingRef.current,
      });
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

  // ---- Send message ----

  const sendMessage = useCallback(
    async (message: string): Promise<void> => {
      chatDebug("sendMessage_entry", {
        prev_run_count: runsRef.current.size,
        prev_streaming: isStreamingRef.current,
        agent: agentIdRef.current,
        msg_length: message.length,
      });

      if (!agentIdRef.current) {
        throw new Error("No agent selected");
      }

      if (!isConnected) {
        setError("Not connected. Please wait and try again.");
        return;
      }

      setError(null);
      setBudgetError(null);

      const key = agentIdRef.current ? `${agentIdRef.current}:${sessionName}` : null;
      if (key) _needsBootstrap.delete(key);

      const userMsgId = `user-${crypto.randomUUID()}`;

      // Add only the user message. Assistant bubbles are created lazily
      // when OpenClaw emits the first event for a new runId — matches
      // OpenClaw control-ui's implicit-bubble design. See spec §4.
      setMessages((prev) => [
        ...prev,
        { id: userMsgId, role: "user", content: message },
      ]);
      setIsStreaming(true, "sendMessage");

      try {
        sendChat(agentIdRef.current, message);
      } catch (err) {
        const errorMessage = friendlyError(
          err instanceof Error ? err.message : "Failed to send message",
        );
        setError(errorMessage);
        // No placeholder to update — append an error-marked assistant
        // message so the user sees failure feedback.
        const errMsgId = `assistant-${crypto.randomUUID()}`;
        setMessages((prev) => [
          ...prev,
          { id: errMsgId, role: "assistant", content: `Error: ${errorMessage}` },
        ]);
        setIsStreaming(false, "sendMessage-catch");
      }
    },
    [sendChat, isConnected, sessionName],
  );

  // ---- Cancel / stop agent ----

  const cancelMessage = useCallback(async () => {
    chatDebug("cancelMessage_entry", {
      run_count: runsRef.current.size,
      streaming: isStreamingRef.current,
    });
    if (!agentIdRef.current || !isStreaming) return;

    const sessionKey = `agent:${agentIdRef.current}:${sessionName}`;
    try {
      await sendReq("chat.abort", { sessionKey });
    } catch (err) {
      console.warn("Failed to abort agent run:", err);
    }

    // Immediately update local state so the UI feels responsive
    setIsStreaming(false, "cancelMessage");
    finalizeAllActiveRuns();
  }, [isStreaming, sendReq, sessionName, finalizeAllActiveRuns]);

  // ---- Clear messages ----

  const clearMessages = useCallback(() => {
    chatDebug("clearMessages_entry", {
      run_count: runsRef.current.size,
      streaming: isStreamingRef.current,
    });
    setMessages([]);
    const key = agentIdRef.current ? `${agentIdRef.current}:${sessionName}` : null;
    if (key) {
      _messageCache.delete(key);
    }
    setError(null);
    setIsStreaming(false, "clearMessages");
    finalizeAllActiveRuns();
  }, [sessionName, finalizeAllActiveRuns]);

  // ---- Resolve approval (allow-once / allow-always / deny) ----

  const resolveApproval = React.useCallback(
    async (id: string, decision: ExecApprovalDecision): Promise<void> => {
      chatDebug("resolveApproval_start", {
        decision,
        run_count: runsRef.current.size,
        streaming: isStreamingRef.current,
      });
      try {
        const result = await sendReq("exec.approval.resolve", { id, decision });
        chatDebug("resolveApproval_done", {
          decision,
          run_count: runsRef.current.size,
          streaming: isStreamingRef.current,
          result_keys: result && typeof result === "object" ? Object.keys(result as object) : null,
        });
      } catch (err) {
        chatDebug("resolveApproval_error", {
          decision,
          error: err instanceof Error ? err.message : String(err),
        });
        throw err;
      }
    },
    [sendReq],
  );

  // ---- External interface ----

  const externalMessages: AgentMessage[] = useMemo(
    () =>
      messages.map(({ role, content, thinking, toolUses }) => ({
        role,
        content,
        ...(thinking ? { thinking } : {}),
        ...(toolUses?.length ? { toolUses } : {}),
      })),
    [messages],
  );

  const needsBootstrap = !!(
    cacheKey &&
    _needsBootstrap.has(cacheKey) &&
    messages.length === 0 &&
    historyLoadState === "done"
  );

  return {
    messages: externalMessages,
    isStreaming,
    error,
    budgetError,
    sendMessage,
    cancelMessage,
    clearMessages,
    isConnected,
    isLoadingHistory,
    needsBootstrap,
    resolveApproval,
  };
}
