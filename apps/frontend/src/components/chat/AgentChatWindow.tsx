"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ChatInput } from "./ChatInput";
import { MessageList, MessageListHandle } from "./MessageList";
import { useAgentChat, BOOTSTRAP_MESSAGE } from "@/hooks/useAgentChat";
import { useApi } from "@/lib/api";
import { useBilling } from "@/hooks/useBilling";
import { useOrganization } from "@clerk/nextjs";
import { Loader2, AlertTriangle, ArrowDownCircle, RefreshCw, Clock, X } from "lucide-react";
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
  const { account, createCheckout, toggleOverage } = useBilling();
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
  let subtext: string | null = null;
  let actionLabel: string | null = null;

  if (isOrg && !isOrgAdmin) {
    message = "Your organization has reached its usage limit. Contact your admin.";
  } else if (!budgetError.is_subscribed) {
    message = "You've reached your free tier limit. Subscribe to continue.";
    actionLabel = "Subscribe";
  } else if (budgetError.overage_available && !budgetError.overage_enabled) {
    message = "Your included LLM budget is used up. Enable pay-as-you-go to continue.";
    subtext = "Overage is billed at 1.4x standard rates";
    actionLabel = "Enable pay-as-you-go";
  } else if (account?.overage_enabled && account?.overage_limit !== null) {
    message = "You've reached your usage limit for this billing period.";
    subtext = `Overage limit: $${account.overage_limit.toFixed(2)}`;
  } else {
    message = "You've reached your usage limit for this billing period.";
  }

  return (
    <div className="mx-4 mb-2 p-3 bg-[#fff8e1] border border-[#ffe0b2] rounded-lg flex items-center gap-3">
      <AlertTriangle className="h-4 w-4 text-[#8a6a22] shrink-0" />
      <div className="flex-1">
        <p className="text-sm text-[#5a4510]">{message}</p>
        {subtext && (
          <p className="text-xs text-[#8a6a22] mt-0.5">{subtext}</p>
        )}
      </div>
      {actionLabel && (
        <Button
          size="sm"
          variant="outline"
          className="shrink-0 border-[#ffe0b2] text-[#5a4510] hover:bg-[#fff3cc]"
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
// Approach-Limit Banner
// =============================================================================

const SNOOZE_DURATION_MS = 24 * 60 * 60 * 1000; // 24 hours

function getBudgetSnooze(threshold: number): boolean {
  try {
    const raw = localStorage.getItem(`isol8_budget_snooze_${threshold}`);
    if (!raw) return false;
    const snoozedUntil = JSON.parse(raw) as number;
    if (Date.now() < snoozedUntil) return true;
    localStorage.removeItem(`isol8_budget_snooze_${threshold}`);
    return false;
  } catch {
    return false;
  }
}

function setBudgetSnooze(threshold: number): void {
  localStorage.setItem(
    `isol8_budget_snooze_${threshold}`,
    JSON.stringify(Date.now() + SNOOZE_DURATION_MS),
  );
}

function ApproachLimitBanner() {
  const { account, isSubscribed, toggleOverage } = useBilling();
  const [dismissed75, setDismissed75] = useState(() => getBudgetSnooze(75));
  const [dismissed90, setDismissed90] = useState(() => getBudgetSnooze(90));
  const [loading, setLoading] = useState(false);

  if (!account || !isSubscribed) return null;

  const pct = account.budget_percent;

  if (pct >= 90 && !dismissed90) {
    return (
      <div className="mx-4 mb-2 p-3 bg-[#fff3e0] border border-[#ffcc80] rounded-lg flex items-center gap-3">
        <AlertTriangle className="h-4 w-4 text-[#e65100] shrink-0" />
        <div className="flex-1">
          <p className="text-sm text-[#5a3500]">
            You&apos;ve used {Math.round(pct)}% of your included LLM budget. Consider enabling pay-as-you-go.
          </p>
          <p className="text-xs text-[#8a6200] mt-0.5">
            Overage is billed at 1.4x standard rates
          </p>
        </div>
        {!account.overage_enabled && (
          <Button
            size="sm"
            variant="outline"
            className="shrink-0 border-[#ffcc80] text-[#5a3500] hover:bg-[#ffe0b2]"
            onClick={async () => {
              setLoading(true);
              try {
                await toggleOverage(true);
              } catch (err) {
                console.error("Failed to enable overage:", err);
              } finally {
                setLoading(false);
              }
            }}
            disabled={loading}
          >
            {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : "Enable pay-as-you-go"}
          </Button>
        )}
        <button
          onClick={() => {
            setBudgetSnooze(90);
            setDismissed90(true);
          }}
          className="text-[#e65100] hover:text-[#e65100] shrink-0"
          aria-label="Dismiss"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    );
  }

  if (pct >= 75 && !dismissed75) {
    return (
      <div className="mx-4 mb-2 p-3 bg-[#fff8e1] border border-[#ffe082] rounded-lg flex items-center gap-3">
        <AlertTriangle className="h-4 w-4 text-[#f9a825] shrink-0" />
        <p className="text-sm text-[#5a4510] flex-1">
          You&apos;ve used {Math.round(pct)}% of your included LLM budget this month.
        </p>
        <button
          onClick={() => {
            setBudgetSnooze(75);
            setDismissed75(true);
          }}
          className="text-[#f9a825] hover:text-[#f9a825] shrink-0"
          aria-label="Dismiss"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    );
  }

  return null;
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
      <div className="mx-4 mb-2 p-3 bg-[#e8f5e9] border border-[#c8e6c9] rounded-lg flex items-center gap-3">
        <Loader2 className="h-4 w-4 text-[#2d8a4e] shrink-0 animate-spin" />
        <p className="text-sm text-[#1a5c32] flex-1">Updating your agent...</p>
      </div>
    );
  }

  // Org member (non-admin) -- info only
  if (isOrg && !isOrgAdmin) {
    return (
      <div className="mx-4 mb-2 p-3 bg-[#e8f5e9] border border-[#c8e6c9] rounded-lg flex items-center gap-3">
        <RefreshCw className="h-4 w-4 text-[#2d8a4e] shrink-0" />
        <p className="text-sm text-[#1a5c32] flex-1">
          An update is available. Your admin can apply it.
        </p>
        <button
          onClick={() => setDismissed(true)}
          className="text-[#2d8a4e] hover:text-[#2d8a4e] shrink-0"
          aria-label="Dismiss"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    );
  }

  return (
    <div className="mx-4 mb-2 p-3 bg-[#e8f5e9] border border-[#c8e6c9] rounded-lg">
      <div className="flex items-center gap-3">
        <RefreshCw className="h-4 w-4 text-[#2d8a4e] shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-sm text-[#1a5c32]">
            Update available: {description}
          </p>
          <p className="text-xs text-[#2d7a50] mt-0.5">
            Your agent needs a brief restart (~30s) to apply.
          </p>
        </div>
        <button
          onClick={() => setDismissed(true)}
          className="text-[#2d8a4e] hover:text-[#2d8a4e] shrink-0"
          aria-label="Dismiss"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="flex items-center gap-2 mt-2 ml-7">
        <Button
          size="sm"
          variant="outline"
          className="shrink-0 border-[#c8e6c9] text-[#1a5c32] hover:bg-[#c8e6c9]"
          onClick={() => handleApplyNow(firstUpdate.update_id)}
        >
          <RefreshCw className="h-3 w-3 mr-1" />
          Update Now
        </Button>
        <Button
          size="sm"
          variant="outline"
          className="shrink-0 border-[#c8e6c9] text-[#1a5c32] hover:bg-[#c8e6c9]"
          onClick={() => handleScheduleTonight(firstUpdate.update_id)}
        >
          <Clock className="h-3 w-3 mr-1" />
          Tonight at 2 AM
        </Button>
        <Button
          size="sm"
          variant="outline"
          className="shrink-0 border-[#c8e6c9] text-[#1a5c32] hover:bg-[#c8e6c9]"
          onClick={() => handleRemindLater(firstUpdate.update_id)}
        >
          Remind Me Later
        </Button>
      </div>
    </div>
  );
}

// =============================================================================
// Downgrade Banner
// =============================================================================

function DowngradeBanner() {
  const { wasDowngraded, clearDowngrade } = useBilling();

  if (!wasDowngraded) return null;

  return (
    <div className="mx-4 mb-2 p-3 bg-[#fce4ec] border border-[#f8bbd0] rounded-lg flex items-center gap-3">
      <ArrowDownCircle className="h-4 w-4 text-[#c62828] shrink-0" />
      <p className="text-sm text-[#a5311f] flex-1">
        Your subscription has ended. You&apos;re now on the free tier with $2 lifetime usage.
      </p>
      <button
        onClick={clearDowngrade}
        className="text-[#c62828] hover:text-[#c62828] shrink-0"
        aria-label="Dismiss"
      >
        <X className="h-4 w-4" />
      </button>
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
      <div className="flex flex-col h-full bg-[#faf7f2]">
        <div className="flex-1 flex flex-col">
          {messages.length > 0 && (
            <MessageList ref={messageListRef} messages={messages} isTyping={isTyping} />
          )}
          <div className="p-4 m-4 bg-[#fce4ec] border border-[#f8bbd0] text-[#a5311f] rounded-lg">
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
      <div className="flex flex-col h-full bg-[#faf7f2]">
        <div className="flex-1 flex items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-[#8a8578]" />
        </div>
      </div>
    );
  }

  if (isInitialState) {
    return (
      <div className="flex flex-col h-full bg-[#faf7f2]">
        <div className="flex-1 flex flex-col items-center justify-center p-4">
          <div className="text-center mb-8">
            <div className="mb-6 flex justify-center">
              <svg width="56" height="56" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
                <rect width="100" height="100" rx="22" fill="#06402B" />
                <text x="50" y="68" textAnchor="middle" fontFamily="var(--font-lora-serif), serif" fontStyle="italic" fontSize="52" fill="white">8</text>
              </svg>
            </div>
            <h1 className="text-3xl mb-3 text-[#1a1a1a] tracking-tight font-lora">
              {agentId ?? "Select an agent"}
            </h1>
            <p className="text-[#8a8578] text-base">
              Start a conversation with your agent
            </p>
          </div>
          <div className="w-full max-w-2xl">
            <UpdateBanner />
            <DowngradeBanner />
            <ApproachLimitBanner />
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
    <div className="flex flex-col h-full min-h-0 bg-[#faf7f2]">
      <MessageList ref={messageListRef} messages={messages} isTyping={isTyping} />
      <UpdateBanner />
      <DowngradeBanner />
      <ApproachLimitBanner />
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
