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

import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import { useGateway, type ChatIncomingMessage, type BudgetExceededPayload } from "@/hooks/useGateway";

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

export interface ToolUse {
  tool: string;
  toolCallId?: string;
  status: "running" | "done" | "error";
}

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
  const { isConnected, sendChat, onChatMessage, sendReq } = useGateway();

  // Cache key includes session name so org members don't share history cache
  const cacheKey = agentId ? `${agentId}:${sessionName}` : null;

  const [messages, setMessages] = useState<InternalMessage[]>(
    () => (cacheKey ? _messageCache.get(cacheKey) ?? [] : []),
  );
  const [isStreaming, setIsStreaming] = useState(false);
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
      // Only process if we're currently streaming
      if (!currentAssistantIdRef.current) return;

      // Drop messages meant for a different agent. Heartbeat and
      // update_available don't carry agent_id because they aren't tied to
      // a specific run; everything else must match the active agent.
      const isUntaggedBroadcast =
        msg.type === "heartbeat" || msg.type === "update_available";
      if (!isUntaggedBroadcast && msg.agent_id !== agentIdRef.current) return;

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
        setIsStreaming(false);
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
          setIsStreaming(false);
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
        setIsStreaming(false);
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
            prev.map((m) =>
              m.id === currentAssistantIdRef.current
                ? {
                    ...m,
                    toolUses: [
                      ...(m.toolUses || []),
                      {
                        tool: msg.tool,
                        toolCallId: msg.toolCallId,
                        status: "running" as const,
                      },
                    ],
                  }
                : m,
            ),
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
                return isRunning && (matchesCallId || matchesName)
                  ? { ...t, status: nextStatus as "done" | "error" }
                  : t;
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

  // ---- Send message ----

  const sendMessage = useCallback(
    async (message: string): Promise<void> => {
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
      setIsStreaming(true);

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
        setIsStreaming(false);
        currentAssistantIdRef.current = null;
        streamContentRef.current = "";
      }
    },
    [sendChat, isConnected, sessionName],
  );

  // ---- Cancel / stop agent ----

  const cancelMessage = useCallback(async () => {
    if (!agentIdRef.current || !isStreaming) return;

    const sessionKey = `agent:${agentIdRef.current}:${sessionName}`;
    try {
      await sendReq("chat.abort", { sessionKey });
    } catch (err) {
      console.warn("Failed to abort agent run:", err);
    }

    // Immediately update local state so the UI feels responsive
    setIsStreaming(false);
    currentAssistantIdRef.current = null;
    streamContentRef.current = "";
  }, [isStreaming, sendReq, sessionName]);

  // ---- Clear messages ----

  const clearMessages = useCallback(() => {
    setMessages([]);
    const key = agentIdRef.current ? `${agentIdRef.current}:${sessionName}` : null;
    if (key) {
      _messageCache.delete(key);
    }
    setError(null);
    setIsStreaming(false);
    currentAssistantIdRef.current = null;
    streamContentRef.current = "";
  }, [sessionName]);

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
  };
}
