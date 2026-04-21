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

  const currentAssistantIdRef = useRef<string | null>(null);
  const streamContentRef = useRef<string>("");
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
          ref: currentAssistantIdRef.current,
          streaming: isStreamingRef.current,
          error_code: (msg as { code?: string }).code,
          // NOTE: deliberately do not include the error message string — it
          // can carry user-provided content (budget/tier labels, partial
          // agent output on aborted runs).
          has_error_message: Boolean((msg as { message?: string }).message),
        });
      }

      // Only process if we're currently streaming
      if (!currentAssistantIdRef.current) {
        if (msg.type !== "chunk" && msg.type !== "heartbeat") {
          chatDebug("chat_msg_dropped_no_ref", { msg_type: msg.type });
        }
        return;
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
        // OpenClaw sends cumulative text (full response so far) in each
        // chunk, so we replace rather than append — matching how OpenClaw's
        // own frontend handles streaming.
        streamContentRef.current = msg.content;
        const updatedContent = streamContentRef.current;
        setMessages((prev) =>
          prev.map((m) =>
            m.id === currentAssistantIdRef.current
              ? { ...m, content: updatedContent }
              : m,
          ),
        );
        return;
      }

      if (msg.type === "done") {
        setIsStreaming(false, "done-event");
        currentAssistantIdRef.current = null;
        streamContentRef.current = "";
        return;
      }

      if (msg.type === "error") {
        // Handle budget exceeded errors specially
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
          // Remove the empty assistant message placeholder
          if (currentAssistantIdRef.current) {
            setMessages((prev) =>
              prev.filter((m) => m.id !== currentAssistantIdRef.current),
            );
          }
          setIsStreaming(false, "error-budget");
          currentAssistantIdRef.current = null;
          streamContentRef.current = "";
          return;
        }

        const displayError = friendlyError(msg.message);
        if (currentAssistantIdRef.current) {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === currentAssistantIdRef.current
                ? { ...m, content: displayError }
                : m,
            ),
          );
        }
        setError(displayError);
        setIsStreaming(false, "error-generic");
        currentAssistantIdRef.current = null;
        streamContentRef.current = "";
        return;
      }

      if (msg.type === "thinking") {
        // Streamed thinking events carry the cumulative thinking text, so
        // replace rather than append. The chat.final batch sends a single
        // event with the full text — replace works for that too.
        if (currentAssistantIdRef.current) {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === currentAssistantIdRef.current
                ? { ...m, thinking: msg.content }
                : m,
            ),
          );
        }
        return;
      }

      if (msg.type === "tool_start") {
        if (currentAssistantIdRef.current) {
          setMessages((prev) =>
            prev.map((m) => {
              if (m.id !== currentAssistantIdRef.current) return m;
              const existing = m.toolUses ?? [];
              // If an approval request already created a ToolUse for this call
              // (race where exec.approval.requested lands before tool_start),
              // merge into that entry rather than appending a duplicate.
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
                  // Keep pending-approval/denied if approval already landed;
                  // only default to "running" when we had no prior status.
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
        }
        return;
      }

      if (msg.type === "tool_end" || msg.type === "tool_error") {
        const nextStatus = msg.type === "tool_end" ? "done" : "error";
        if (currentAssistantIdRef.current) {
          setMessages((prev) =>
            prev.map((m) => {
              if (m.id !== currentAssistantIdRef.current) return m;
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
        }
        return;
      }

      if (msg.type === "heartbeat") {
        if (!streamContentRef.current && currentAssistantIdRef.current) {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === currentAssistantIdRef.current
                ? { ...m, content: "Agent is working..." }
                : m,
            ),
          );
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
        ref: currentAssistantIdRef.current,
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

      if (!currentAssistantIdRef.current) return;
      setMessages((prev) =>
        prev.map((m) => {
          if (m.id !== currentAssistantIdRef.current) return m;
          const existing = m.toolUses ?? [];

          // Idempotent: a retry/reconnect can redeliver the same approval.
          // Overwrite the existing entry rather than creating a duplicate.
          const idDupeIdx = existing.findIndex(
            (t) => t.pendingApproval?.id === req.id,
          );
          if (idDupeIdx >= 0) {
            const next = existing.slice();
            next[idDupeIdx] = {
              ...next[idDupeIdx],
              status: "pending-approval",
              pendingApproval: req,
            };
            return { ...m, toolUses: next };
          }

          // Pick the target ToolUse to promote to pending-approval.
          // Prefer exact toolCallId match. For correlationless events, bind
          // to the NEWEST running exec so concurrent commands don't misroute
          // the card to an older, unrelated call.
          let targetIdx = -1;
          if (correlation) {
            targetIdx = existing.findIndex(
              (t) => t.toolCallId === correlation,
            );
          } else {
            for (let i = existing.length - 1; i >= 0; i--) {
              if (existing[i].tool === "exec" && existing[i].status === "running") {
                targetIdx = i;
                break;
              }
            }
          }

          if (targetIdx >= 0) {
            const next = existing.slice();
            next[targetIdx] = {
              ...next[targetIdx],
              status: "pending-approval",
              pendingApproval: req,
            };
            return { ...m, toolUses: next };
          }

          return {
            ...m,
            toolUses: [
              ...existing,
              {
                tool: "exec",
                toolCallId: correlation,
                status: "pending-approval",
                pendingApproval: req,
              },
            ],
          };
        }),
      );
    });

    const unsubResolved = onEvent((eventName, data) => {
      if (eventName !== "exec.approval.resolved") return;
      const payload = data as { id?: string; decision?: ExecApprovalDecision };
      chatDebug("approval_resolved_event_rx", {
        id: payload?.id,
        decision: payload?.decision,
        ref: currentAssistantIdRef.current,
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
        prev_ref: currentAssistantIdRef.current,
        prev_streaming: isStreamingRef.current,
        agent: agentIdRef.current,
        // shape only — no raw user content
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

      // Clear bootstrap flag once user sends their first message
      const key = agentIdRef.current ? `${agentIdRef.current}:${sessionName}` : null;
      if (key) _needsBootstrap.delete(key);

      const userMsgId = `user-${crypto.randomUUID()}`;
      const assistantMsgId = `assistant-${crypto.randomUUID()}`;

      currentAssistantIdRef.current = assistantMsgId;
      streamContentRef.current = "";

      setMessages((prev) => [
        ...prev,
        { id: userMsgId, role: "user", content: message },
        { id: assistantMsgId, role: "assistant", content: "" },
      ]);
      setIsStreaming(true, "sendMessage");

      try {
        sendChat(agentIdRef.current, message);
      } catch (err) {
        const errorMessage = friendlyError(
          err instanceof Error ? err.message : "Failed to send message",
        );
        setError(errorMessage);
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMsgId
              ? { ...m, content: errorMessage }
              : m,
          ),
        );
        setIsStreaming(false, "sendMessage-catch");
        currentAssistantIdRef.current = null;
        streamContentRef.current = "";
      }
    },
    [sendChat, isConnected, sessionName],
  );

  // ---- Cancel / stop agent ----

  const cancelMessage = useCallback(async () => {
    chatDebug("cancelMessage_entry", {
      ref: currentAssistantIdRef.current,
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
    currentAssistantIdRef.current = null;
    streamContentRef.current = "";
  }, [isStreaming, sendReq, sessionName]);

  // ---- Clear messages ----

  const clearMessages = useCallback(() => {
    chatDebug("clearMessages_entry", {
      ref: currentAssistantIdRef.current,
      streaming: isStreamingRef.current,
    });
    setMessages([]);
    const key = agentIdRef.current ? `${agentIdRef.current}:${sessionName}` : null;
    if (key) {
      _messageCache.delete(key);
    }
    setError(null);
    setIsStreaming(false, "clearMessages");
    currentAssistantIdRef.current = null;
    streamContentRef.current = "";
  }, [sessionName]);

  // ---- Resolve approval (allow-once / allow-always / deny) ----

  const resolveApproval = React.useCallback(
    async (id: string, decision: ExecApprovalDecision): Promise<void> => {
      chatDebug("resolveApproval_start", {
        decision,
        ref: currentAssistantIdRef.current,
        streaming: isStreamingRef.current,
      });
      try {
        const result = await sendReq("exec.approval.resolve", { id, decision });
        chatDebug("resolveApproval_done", {
          decision,
          ref: currentAssistantIdRef.current,
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
