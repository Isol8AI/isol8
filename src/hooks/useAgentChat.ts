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

import { useState, useCallback, useRef, useEffect } from "react";
import { useGateway, type ChatIncomingMessage } from "@/hooks/useGateway";

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
// Types
// =============================================================================

export interface ToolUse {
  tool: string;
  status: "running" | "done";
}

export interface AgentMessage {
  role: "user" | "assistant";
  content: string;
  toolUses?: ToolUse[];
}

export interface UseAgentChatReturn {
  messages: AgentMessage[];
  isStreaming: boolean;
  error: string | null;
  sendMessage: (message: string) => Promise<void>;
  clearMessages: () => void;
  isConnected: boolean;
}

interface InternalMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
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

// =============================================================================
// Hook
//
// NOTE: Only one useAgentChat instance should be active at a time. The backend
// protocol does not tag chunk/done/error messages with an agent_id, so
// concurrent instances would receive each other's messages. The UI enforces
// this by rendering a single AgentChatWindow.
// =============================================================================

export function useAgentChat(agentId: string | null): UseAgentChatReturn {
  const { isConnected, sendChat, onChatMessage } = useGateway();

  const [messages, setMessages] = useState<InternalMessage[]>(
    () => (agentId ? _messageCache.get(agentId) ?? [] : []),
  );
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const currentAssistantIdRef = useRef<string | null>(null);
  const streamContentRef = useRef<string>("");
  const agentIdRef = useRef(agentId);
  useEffect(() => {
    agentIdRef.current = agentId;
  }, [agentId]);

  // ---- Sync messages to module-level cache ----
  useEffect(() => {
    if (agentId && messages.length > 0) {
      _messageCache.set(agentId, messages);
    }
  }, [agentId, messages]);

  // ---- Chat message handler ----
  // Dependencies are intentionally minimal ([onChatMessage]) because all
  // mutable values are accessed through refs, avoiding stale closures.

  useEffect(() => {
    return onChatMessage((msg: ChatIncomingMessage) => {
      // Only process if we're currently streaming
      if (!currentAssistantIdRef.current) return;

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

      if (msg.type === "tool_start") {
        if (currentAssistantIdRef.current) {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === currentAssistantIdRef.current
                ? {
                    ...m,
                    toolUses: [
                      ...(m.toolUses || []),
                      { tool: msg.tool, status: "running" as const },
                    ],
                  }
                : m,
            ),
          );
        }
        return;
      }

      if (msg.type === "tool_end") {
        if (currentAssistantIdRef.current) {
          setMessages((prev) =>
            prev.map((m) => {
              if (m.id !== currentAssistantIdRef.current) return m;
              const toolUses = (m.toolUses || []).map((t) =>
                t.tool === msg.tool && t.status === "running"
                  ? { ...t, status: "done" as const }
                  : t,
              );
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
    [sendChat, isConnected],
  );

  // ---- Clear messages ----

  const clearMessages = useCallback(() => {
    setMessages([]);
    if (agentIdRef.current) {
      _messageCache.delete(agentIdRef.current);
    }
    setError(null);
    setIsStreaming(false);
    currentAssistantIdRef.current = null;
    streamContentRef.current = "";
  }, []);

  // ---- External interface ----

  const externalMessages: AgentMessage[] = messages.map(({ role, content, toolUses }) => ({
    role,
    content,
    ...(toolUses?.length ? { toolUses } : {}),
  }));

  return {
    messages: externalMessages,
    isStreaming,
    error,
    sendMessage,
    clearMessages,
    isConnected,
  };
}
