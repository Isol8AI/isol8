"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ChatInput } from "./ChatInput";
import { ConnectionStatusBar } from "./ConnectionStatusBar";
import { MessageList, MessageListHandle } from "./MessageList";
import { useAgentChat, BOOTSTRAP_MESSAGE } from "@/hooks/useAgentChat";
import { useApi } from "@/lib/api";
import { useBilling } from "@/hooks/useBilling";
import { useOrganization } from "@clerk/nextjs";
import { Loader2, AlertTriangle, RefreshCw, Clock, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useGateway } from "@/hooks/useGateway";

import type { ToolUse } from "@/hooks/useAgentChat";
import type { BudgetExceededPayload, ChatIncomingMessage } from "@/hooks/useGateway";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  thinking?: string;
  model?: string;
  toolUses?: ToolUse[];
}

interface AgentChatWindowProps {
  agentId: string | null;
}

function BudgetExceededBanner({
  budgetError,
}: {
  budgetError: BudgetExceededPayload;
}) {
  const { createCheckout, toggleOverage } = useBilling();
  const { organization, membership } = useOrganization();
  const [loading, setLoading] = useState(false);

  const isOrg = !!organization;
  const isOrgAdmin = membership?.role === "org:admin";

  const handleAction = useCallback(async () => {
    setLoading(true);
    try {
      if (!budgetError.is_subscribed) {
        await createCheckout("starter");
      } else if (budgetError.overage_available && !budgetError.overage_enabled) {
        await toggleOverage(true);
      }
    } catch (err) {
      console.error("Budget action failed:", err);
    } finally {
      setLoading(false);
    }
  }, [budgetError, createCheckout, toggleOverage]);

  let message: string;
  let actionLabel: string | null = null;

  if (isOrg && !isOrgAdmin) {
    message = "Your organization has reached its usage limit. Contact your admin.";
  } else if (!budgetError.is_subscribed) {
    message = "You've reached your free tier limit. Subscribe to continue.";
    actionLabel = "Subscribe";
  } else if (budgetError.overage_available && !budgetError.overage_enabled) {
    message = "Your included LLM budget is used up. Enable pay-as-you-go to continue.";
    actionLabel = "Enable pay-as-you-go";
  } else {
    message = "You've reached your usage limit for this billing period.";
  }

  return (
    <div className="mx-4 mb-2 p-3 bg-amber-900/20 border border-amber-500/30 rounded-lg flex items-center gap-3">
      <AlertTriangle className="h-4 w-4 text-amber-400 shrink-0" />
      <p className="text-sm text-amber-200 flex-1">{message}</p>
      {actionLabel && (
        <Button
          size="sm"
          variant="outline"
          className="shrink-0 border-amber-500/40 text-amber-200 hover:bg-amber-900/30"
          onClick={handleAction}
          disabled={loading}
        >
          {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : actionLabel}
        </Button>
      )}
    </div>
  );
}

// =============================================================================
// Update Banner
// =============================================================================

interface PendingUpdate {
  update_id: string;
  description: string;
  type: string;
  status: string;
  created_at: string;
  scheduled_at?: string;
}

interface SnoozeEntry {
  update_id: string;
  snoozed_until: number;
}

function getSnooze(updateId: string): SnoozeEntry | null {
  try {
    const raw = localStorage.getItem(`isol8_update_snooze_${updateId}`);
    if (!raw) return null;
    const entry: SnoozeEntry = JSON.parse(raw);
    if (Date.now() < entry.snoozed_until) return entry;
    // Expired -- clean up
    localStorage.removeItem(`isol8_update_snooze_${updateId}`);
    return null;
  } catch {
    return null;
  }
}

function setSnooze(updateId: string, durationMs: number): void {
  const entry: SnoozeEntry = {
    update_id: updateId,
    snoozed_until: Date.now() + durationMs,
  };
  localStorage.setItem(`isol8_update_snooze_${updateId}`, JSON.stringify(entry));
}

function UpdateBanner() {
  const api = useApi();
  const { organization, membership } = useOrganization();
  const { onChatMessage } = useGateway();

  const [updates, setUpdates] = useState<PendingUpdate[]>([]);
  const [applying, setApplying] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  const isOrg = !!organization;
  const isOrgAdmin = membership?.role === "org:admin";

  const fetchUpdates = useCallback(async () => {
    try {
      const data = (await api.get("/container/updates")) as { updates: PendingUpdate[] };
      const pending = (data.updates || []).filter(
        (u) => u.status === "pending" && !getSnooze(u.update_id),
      );
      setUpdates(pending);
      setDismissed(false);
    } catch {
      // Endpoint may not exist yet -- silently ignore
    }
  }, [api]);

  // Fetch on mount
  useEffect(() => {
    fetchUpdates();
  }, [fetchUpdates]);

  // Listen for update_available WS events to trigger refetch
  useEffect(() => {
    const unsub = onChatMessage((msg: ChatIncomingMessage) => {
      if (msg.type === "update_available") {
        fetchUpdates();
      }
    });
    return unsub;
  }, [onChatMessage, fetchUpdates]);

  const handleApplyNow = useCallback(
    async (updateId: string) => {
      setApplying(true);
      try {
        await api.post(`/container/updates/${updateId}/apply`, { schedule: "now" });
        setUpdates((prev) => prev.filter((u) => u.update_id !== updateId));
      } catch (err) {
        console.error("Failed to apply update:", err);
      } finally {
        setApplying(false);
      }
    },
    [api],
  );

  const handleScheduleTonight = useCallback(
    async (updateId: string) => {
      try {
        await api.post(`/container/updates/${updateId}/apply`, { schedule: "tonight" });
        setUpdates((prev) => prev.filter((u) => u.update_id !== updateId));
      } catch (err) {
        console.error("Failed to schedule update:", err);
      }
    },
    [api],
  );

  const handleRemindLater = useCallback(
    async (updateId: string) => {
      try {
        await api.post(`/container/updates/${updateId}/apply`, { schedule: "remind_later" });
      } catch {
        // best-effort
      }
      // Snooze for 4 hours
      setSnooze(updateId, 4 * 60 * 60 * 1000);
      setUpdates((prev) => prev.filter((u) => u.update_id !== updateId));
    },
    [api],
  );

  if (dismissed || updates.length === 0) return null;

  const firstUpdate = updates[0];
  const description =
    updates.length > 1
      ? `${updates.length} updates available`
      : firstUpdate.description;

  // During apply -- show spinner state
  if (applying) {
    return (
      <div className="mx-4 mb-2 p-3 bg-blue-900/20 border border-blue-500/30 rounded-lg flex items-center gap-3">
        <Loader2 className="h-4 w-4 text-blue-400 shrink-0 animate-spin" />
        <p className="text-sm text-blue-200 flex-1">Updating your agent...</p>
      </div>
    );
  }

  // Org member (non-admin) -- info only
  if (isOrg && !isOrgAdmin) {
    return (
      <div className="mx-4 mb-2 p-3 bg-blue-900/20 border border-blue-500/30 rounded-lg flex items-center gap-3">
        <RefreshCw className="h-4 w-4 text-blue-400 shrink-0" />
        <p className="text-sm text-blue-200 flex-1">
          An update is available. Your admin can apply it.
        </p>
        <button
          onClick={() => setDismissed(true)}
          className="text-blue-400 hover:text-blue-300 shrink-0"
          aria-label="Dismiss"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    );
  }

  return (
    <div className="mx-4 mb-2 p-3 bg-blue-900/20 border border-blue-500/30 rounded-lg">
      <div className="flex items-center gap-3">
        <RefreshCw className="h-4 w-4 text-blue-400 shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-sm text-blue-200">
            Update available: {description}
          </p>
          <p className="text-xs text-blue-300/70 mt-0.5">
            Your agent needs a brief restart (~30s) to apply.
          </p>
        </div>
        <button
          onClick={() => setDismissed(true)}
          className="text-blue-400 hover:text-blue-300 shrink-0"
          aria-label="Dismiss"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="flex items-center gap-2 mt-2 ml-7">
        <Button
          size="sm"
          variant="outline"
          className="shrink-0 border-blue-500/40 text-blue-200 hover:bg-blue-900/30"
          onClick={() => handleApplyNow(firstUpdate.update_id)}
        >
          <RefreshCw className="h-3 w-3 mr-1" />
          Update Now
        </Button>
        <Button
          size="sm"
          variant="outline"
          className="shrink-0 border-blue-500/40 text-blue-200 hover:bg-blue-900/30"
          onClick={() => handleScheduleTonight(firstUpdate.update_id)}
        >
          <Clock className="h-3 w-3 mr-1" />
          Tonight at 2 AM
        </Button>
        <Button
          size="sm"
          variant="outline"
          className="shrink-0 border-blue-500/40 text-blue-200 hover:bg-blue-900/30"
          onClick={() => handleRemindLater(firstUpdate.update_id)}
        >
          Remind Me Later
        </Button>
      </div>
    </div>
  );
}

export function AgentChatWindow({
  agentId,
}: AgentChatWindowProps): React.ReactElement {
  const {
    messages: chatMessages,
    isStreaming,
    error: chatError,
    budgetError,
    sendMessage,
    cancelMessage,
    clearMessages,
    isLoadingHistory,
    needsBootstrap,
  } = useAgentChat(agentId);

  const api = useApi();
  const [isUploading, setIsUploading] = useState(false);
  const messageListRef = useRef<MessageListHandle>(null);

  const isInitialState = chatMessages.length === 0;
  const isTyping = isStreaming;
  const isBudgetExceeded = !!budgetError;

  const prevAgentIdRef = useRef<string | null | undefined>(undefined);

  useEffect(() => {
    if (
      prevAgentIdRef.current !== undefined &&
      prevAgentIdRef.current !== agentId
    ) {
      clearMessages();
    }
    prevAgentIdRef.current = agentId;
  }, [agentId, clearMessages]);

  const handleSend = useCallback(
    async (content: string, files?: File[]): Promise<void> => {
      try {
        let message = content;

        if (files && files.length > 0) {
          setIsUploading(true);
          try {
            const result = await api.uploadFiles(files);
            const fileList = result.uploaded
              .map((f) => `- ${f.filename} → ${f.path}`)
              .join("\n");
            const fileNotice = `[The user uploaded files to your workspace. You can read them at these paths:\n${fileList}]\n\n`;
            message = fileNotice + message;
          } catch (err) {
            console.error("Upload failed:", err);
            const errorMsg = err instanceof Error ? err.message : "Upload failed";
            // Still send the text message but note the upload failure
            message = `[File upload failed: ${errorMsg}]\n\n` + message;
          } finally {
            setIsUploading(false);
          }
        }

        if (message.trim()) {
          await sendMessage(message);
          setTimeout(() => messageListRef.current?.scrollToBottom(), 50);
        }
      } catch (err) {
        console.error("Failed to send message:", err);
      }
    },
    [sendMessage, api],
  );

  const messages: Message[] = useMemo(
    () =>
      chatMessages.map((msg, i) => ({
        id: String(i),
        role: msg.role,
        content: msg.content,
        ...(msg.thinking ? { thinking: msg.thinking } : {}),
        ...(msg.toolUses?.length ? { toolUses: msg.toolUses } : {}),
      })),
    [chatMessages],
  );

  if (chatError) {
    return (
      <div className="flex flex-col h-full bg-background/20">
        <ConnectionStatusBar />
        <div className="flex-1 flex flex-col">
          {messages.length > 0 && (
            <MessageList ref={messageListRef} messages={messages} isTyping={isTyping} />
          )}
          <div className="p-4 m-4 bg-red-900/20 text-red-300 rounded-lg">
            <p className="font-medium">Error</p>
            <p className="text-sm">{chatError}</p>
          </div>
          <ChatInput onSend={handleSend} onStop={cancelMessage} disabled={isTyping} isStreaming={isStreaming} isUploading={isUploading} />
        </div>
      </div>
    );
  }

  if (isLoadingHistory) {
    return (
      <div className="flex flex-col h-full bg-background/20">
        <ConnectionStatusBar />
        <div className="flex-1 flex items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-white/40" />
        </div>
      </div>
    );
  }

  if (isInitialState) {
    return (
      <div className="flex flex-col h-full bg-background/20">
        <ConnectionStatusBar />
        <div className="flex-1 flex flex-col items-center justify-center p-4">
          <div className="text-center mb-8">
            <h1 className="text-4xl font-bold mb-3 text-foreground tracking-tight font-host">
              {agentId ?? "Select an agent"}
            </h1>
            <p className="text-muted-foreground text-lg font-light">
              Start a conversation with your agent
            </p>
          </div>
          <div className="w-full max-w-2xl">
            <UpdateBanner />
            {budgetError && <BudgetExceededBanner budgetError={budgetError} />}
            <ChatInput
              onSend={handleSend}
              onStop={cancelMessage}
              disabled={isTyping || !agentId}
              isStreaming={isStreaming}
              centered
              isUploading={isUploading}
              suggestedMessage={needsBootstrap ? BOOTSTRAP_MESSAGE : undefined}
              budgetExceeded={isBudgetExceeded}
            />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full min-h-0 bg-background/20">
      <ConnectionStatusBar />
      <MessageList ref={messageListRef} messages={messages} isTyping={isTyping} />
      <UpdateBanner />
      {budgetError && <BudgetExceededBanner budgetError={budgetError} />}
      <ChatInput
        onSend={handleSend}
        onStop={cancelMessage}
        disabled={isTyping}
        isStreaming={isStreaming}
        isUploading={isUploading}
        budgetExceeded={isBudgetExceeded}
      />
    </div>
  );
}
