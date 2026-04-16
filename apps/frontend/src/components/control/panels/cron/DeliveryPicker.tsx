// apps/frontend/src/components/control/panels/cron/DeliveryPicker.tsx
"use client";

import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useGatewayRpc } from "@/hooks/useGatewayRpc";
import { cn } from "@/lib/utils";
import type {
  CronDelivery,
  CronDeliveryMode,
  CronFailureDestination,
} from "./types";

// --- Channel metadata ---

const CHAT_CHANNEL_ID = "__chat__";
const CHAT_CHANNEL_LABEL = "Chat";

const CHANNEL_META: Record<string, { helpTo: string; hasThreads: boolean }> = {
  telegram: { helpTo: "@handle or chat ID", hasThreads: true },
  discord: { helpTo: "#channel or user", hasThreads: true },
  slack: { helpTo: "@user or #channel", hasThreads: true },
  whatsapp: { helpTo: "+1234567890", hasThreads: false },
  signal: { helpTo: "+1234567890", hasThreads: false },
};

function channelLabel(id: string): string {
  if (id === CHAT_CHANNEL_ID) return CHAT_CHANNEL_LABEL;
  return id.charAt(0).toUpperCase() + id.slice(1);
}

// --- Channels.status shape ---

interface AccountSnapshot {
  accountId: string;
  [key: string]: unknown;
}

interface ChannelsStatusResponse {
  channelAccounts?: Record<string, AccountSnapshot[]>;
}

function useChannelOptions(): {
  options: { id: string; label: string }[];
  accounts: Record<string, AccountSnapshot[]>;
} {
  const { data } = useGatewayRpc<ChannelsStatusResponse>("channels.status", {
    probe: false,
  });

  return useMemo(() => {
    const accounts = data?.channelAccounts ?? {};
    const linkedChannels = Object.entries(accounts)
      .filter(([, list]) => Array.isArray(list) && list.length > 0)
      .map(([id]) => ({ id, label: channelLabel(id) }));
    return {
      options: [
        { id: CHAT_CHANNEL_ID, label: CHAT_CHANNEL_LABEL },
        ...linkedChannels,
      ],
      accounts,
    };
  }, [data]);
}

// --- URL validation ---

export function isValidWebhookUrl(url: string): boolean {
  if (!url.trim()) return false;
  try {
    const u = new URL(url.trim());
    return u.protocol === "http:" || u.protocol === "https:";
  } catch {
    return false;
  }
}

// --- Failure-destination translation ---
//
// DeliveryPicker works in terms of CronDelivery (mode includes "none").
// For the nested failure picker we translate to/from CronFailureDestination
// (no "none", no threadId/bestEffort).

function failureDestToDelivery(fd: CronFailureDestination | undefined): CronDelivery | undefined {
  if (!fd) return undefined;
  return {
    mode: fd.mode ?? "announce",
    channel: fd.channel,
    to: fd.to,
    accountId: fd.accountId,
  };
}

function deliveryToFailureDest(d: CronDelivery | undefined): CronFailureDestination | undefined {
  if (!d) return undefined;
  if (d.mode === "none") return undefined;
  const out: CronFailureDestination = { mode: d.mode };
  if (d.channel !== undefined) out.channel = d.channel;
  if (d.to !== undefined) out.to = d.to;
  if (d.accountId !== undefined) out.accountId = d.accountId;
  return out;
}

// --- Props ---

export interface DeliveryPickerProps {
  value: CronDelivery | undefined;
  onChange: (d: CronDelivery | undefined) => void;
  /** Defaults to "Delivery". Nested picker uses a different label. */
  label?: string;
  /**
   * When true, this picker is nested inside a failure-destination block.
   * Nested pickers hide the "send failures elsewhere" sub-block (no infinite
   * nesting) and never render the "None" mode (the parent toggle handles
   * "not set").
   */
  nested?: boolean;
}

// --- Component ---

export function DeliveryPicker({
  value,
  onChange,
  label = "Delivery",
  nested = false,
}: DeliveryPickerProps) {
  const { options, accounts } = useChannelOptions();

  const delivery: CronDelivery = value ?? { mode: nested ? "announce" : "none" };
  const mode: CronDeliveryMode = delivery.mode;

  const currentChannelId = delivery.channel ?? CHAT_CHANNEL_ID;
  const currentMeta =
    delivery.channel && CHANNEL_META[delivery.channel]
      ? CHANNEL_META[delivery.channel]
      : null;
  const channelAccounts = delivery.channel ? (accounts[delivery.channel] ?? []) : [];
  const hideAccountPicker = channelAccounts.length <= 1;

  // --- Handlers ---

  function setMode(next: CronDeliveryMode) {
    // Always preserve a previously-configured failureDestination across mode
    // changes — toggling delivery mode must not silently drop the user's
    // already-configured failure route. The nested picker's "Remove failure
    // destination" button is the only way to clear it.
    const carryFailure: Pick<CronDelivery, "failureDestination"> = delivery
      .failureDestination
      ? { failureDestination: delivery.failureDestination }
      : {};

    if (next === "none") {
      onChange({ mode: "none", ...carryFailure });
      return;
    }
    if (next === "announce") {
      onChange({
        mode: "announce",
        // Preserve any prior channel-specific fields when switching from
        // announce back to announce (no-op guard for edge cases).
        ...(mode === "announce"
          ? {
              channel: delivery.channel,
              to: delivery.to,
              threadId: delivery.threadId,
              accountId: delivery.accountId,
            }
          : {}),
        ...carryFailure,
      });
      return;
    }
    // webhook: `to` holds the URL; drop channel/threadId/accountId.
    onChange({
      mode: "webhook",
      to: mode === "webhook" ? delivery.to : "",
      ...carryFailure,
    });
  }

  function setChannel(channelId: string) {
    if (channelId === CHAT_CHANNEL_ID) {
      onChange({
        mode: "announce",
        channel: undefined,
        to: undefined,
        threadId: undefined,
        accountId: undefined,
        failureDestination: delivery.failureDestination,
      });
      return;
    }
    const list = accounts[channelId] ?? [];
    const autoAccountId = list.length === 1 ? list[0].accountId : undefined;
    onChange({
      mode: "announce",
      channel: channelId,
      to: delivery.channel === channelId ? delivery.to : "",
      threadId: delivery.channel === channelId ? delivery.threadId : undefined,
      accountId: autoAccountId,
      failureDestination: delivery.failureDestination,
    });
  }

  function patch(fields: Partial<CronDelivery>) {
    onChange({ ...delivery, ...fields });
  }

  // --- Failure destination ---

  const [failureOpen, setFailureOpen] = useState<boolean>(
    !!delivery.failureDestination,
  );

  const handleFailureDestChange = (inner: CronDelivery | undefined) => {
    const fd = deliveryToFailureDest(inner);
    onChange({ ...delivery, failureDestination: fd });
  };

  const closeFailureDest = () => {
    setFailureOpen(false);
    onChange({ ...delivery, failureDestination: undefined });
  };

  // --- Render helpers ---

  const webhookUrl = mode === "webhook" ? (delivery.to ?? "") : "";
  const webhookUrlInvalid = mode === "webhook" && !!webhookUrl.trim() && !isValidWebhookUrl(webhookUrl);

  const modeButtons: { id: CronDeliveryMode; label: string }[] = nested
    ? [
        { id: "announce", label: "Announce" },
        { id: "webhook", label: "Webhook" },
      ]
    : [
        { id: "none", label: "None" },
        { id: "announce", label: "Announce" },
        { id: "webhook", label: "Webhook" },
      ];

  return (
    <div className="space-y-3" data-testid={nested ? "delivery-picker-nested" : "delivery-picker"}>
      {/* Label + mode segmented buttons */}
      <div className="space-y-2">
        <label className="text-xs font-medium text-[#8a8578]">{label}</label>
        <div className="flex gap-1">
          {modeButtons.map(({ id, label: btnLabel }) => (
            <Button
              key={id}
              variant={mode === id ? "default" : "outline"}
              size="sm"
              onClick={() => setMode(id)}
              className="text-xs"
            >
              {btnLabel}
            </Button>
          ))}
        </div>
      </div>

      {mode === "announce" && (
        <div className="space-y-2">
          {/* Channel dropdown */}
          <div className="space-y-1">
            <label className="text-xs font-medium text-[#8a8578]">Channel</label>
            <select
              value={currentChannelId}
              onChange={(e) => setChannel(e.target.value)}
              aria-label="Delivery channel"
              className="h-8 w-full rounded-md border border-[#e0dbd0] bg-[#faf7f2] px-2 text-sm"
            >
              {options.map((opt) => (
                <option key={opt.id} value={opt.id}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          {/* Account picker (only when a real channel with multiple accounts) */}
          {delivery.channel && !hideAccountPicker && (
            <div className="space-y-1">
              <label className="text-xs font-medium text-[#8a8578]">Account</label>
              <select
                value={delivery.accountId ?? ""}
                onChange={(e) => patch({ accountId: e.target.value || undefined })}
                aria-label="Delivery account"
                className="h-8 w-full rounded-md border border-[#e0dbd0] bg-[#faf7f2] px-2 text-sm"
              >
                <option value="">(select account)</option>
                {channelAccounts.map((acc) => (
                  <option key={acc.accountId} value={acc.accountId}>
                    {acc.accountId}
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* To (always shown for announce mode) */}
          <div className="space-y-1">
            <label className="text-xs font-medium text-[#8a8578]">To</label>
            <Input
              value={delivery.to ?? ""}
              onChange={(e) => patch({ to: e.target.value })}
              placeholder={currentMeta?.helpTo ?? "Chat session"}
              aria-label="Delivery to"
              className="h-8 text-sm"
            />
          </div>

          {/* Thread id (only for channels that support threads) */}
          {currentMeta?.hasThreads && (
            <div className="space-y-1">
              <label className="text-xs font-medium text-[#8a8578]">Thread ID (optional)</label>
              <Input
                value={
                  delivery.threadId === undefined || delivery.threadId === null
                    ? ""
                    : String(delivery.threadId)
                }
                onChange={(e) => {
                  const raw = e.target.value.trim();
                  patch({ threadId: raw === "" ? undefined : raw });
                }}
                placeholder="Thread ID"
                aria-label="Delivery thread id"
                className="h-8 text-sm"
              />
            </div>
          )}
        </div>
      )}

      {mode === "webhook" && (
        <div className="space-y-1">
          <label className="text-xs font-medium text-[#8a8578]">Webhook URL</label>
          <Input
            value={webhookUrl}
            onChange={(e) => patch({ to: e.target.value })}
            placeholder="https://example.com/hook"
            aria-label="Webhook URL"
            className={cn(
              "h-8 text-sm",
              webhookUrlInvalid && "border-destructive focus-visible:ring-destructive",
            )}
          />
          {webhookUrlInvalid && (
            <p className="text-xs text-destructive">Enter a valid http(s) URL.</p>
          )}
        </div>
      )}

      {/* Failure-destination sub-picker (only on top-level picker) */}
      {!nested && mode !== "none" && (
        <div className="pt-1 border-t border-[#e0dbd0]/60">
          {failureOpen ? (
            <div className="space-y-2 pt-2">
              <DeliveryPicker
                value={failureDestToDelivery(delivery.failureDestination)}
                onChange={handleFailureDestChange}
                label="Where to send failure notifications (if different)"
                nested
              />
              <Button
                variant="ghost"
                size="sm"
                onClick={closeFailureDest}
                className="text-xs text-[#8a8578]"
              >
                Remove failure destination
              </Button>
            </div>
          ) : (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setFailureOpen(true)}
              className="text-xs text-[#8a8578]"
            >
              Send failures to a different destination
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
