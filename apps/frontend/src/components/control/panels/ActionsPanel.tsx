"use client";

import { useState, useCallback } from "react";
import {
  Loader2,
  RefreshCw,
  ShieldCheck,
  UserPlus,
  AlertCircle,
  CheckCircle2,
  Radio,
} from "lucide-react";
import { useGatewayRpc, useGatewayRpcMutation } from "@/hooks/useGatewayRpc";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

/* ── Types ─────────────────────────────────────────────── */

interface ConfigSnapshot {
  raw: string | null;
  config: Record<string, unknown>;
  hash?: string;
  valid: boolean;
  [key: string]: unknown;
}

/* ── Channel definitions ───────────────────────────────── */

const PAIRING_CHANNELS = [
  {
    id: "telegram",
    label: "Telegram",
    idLabel: "Numeric Telegram User ID",
    idPlaceholder: "7895038573",
    help: "Enter the numeric user ID shown in the pairing message (not the pairing code).",
    validate: (v: string) => /^\d+$/.test(v) ? null : "Telegram requires a numeric user ID, not the pairing code.",
  },
  {
    id: "discord",
    label: "Discord",
    idLabel: "Discord User ID",
    idPlaceholder: "123456789012345678",
    help: "Enter the numeric Discord user ID (enable Developer Mode to copy it).",
    validate: (v: string) => /^\d+$/.test(v) ? null : "Discord user IDs are numeric.",
  },
  {
    id: "whatsapp",
    label: "WhatsApp",
    idLabel: "Phone Number",
    idPlaceholder: "+1234567890",
    help: "Enter the full phone number with country code.",
    validate: (_v: string) => null,
  },
];

/* ── Component ─────────────────────────────────────────── */

export function ActionsPanel() {
  const callRpc = useGatewayRpcMutation();
  const {
    data: configData,
    mutate: mutateConfig,
  } = useGatewayRpc<ConfigSnapshot>("config.get");

  // Form state
  const [selectedChannel, setSelectedChannel] = useState("telegram");
  const [userIdInput, setUserIdInput] = useState("");

  // Feedback
  const [busy, setBusy] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<{
    type: "success" | "error";
    message: string;
  } | null>(null);

  // Extract current config for display
  const config = configData?.config ?? {};
  const channels = (config.channels ?? {}) as Record<string, Record<string, unknown>>;

  const getCurrentAllowFrom = (channelId: string): string[] => {
    const ch = channels[channelId];
    if (!ch) return [];
    const af = ch.allowFrom;
    if (Array.isArray(af)) return af.map(String);
    return [];
  };

  const getCurrentDmPolicy = (channelId: string): string => {
    const ch = channels[channelId];
    if (!ch) return "pairing";
    return String(ch.dmPolicy ?? "pairing");
  };

  const patchConfig = useCallback(
    async (label: string, patch: Record<string, unknown>, postAction?: () => void) => {
      const snapshot = configData as ConfigSnapshot | undefined;
      if (!snapshot?.hash) {
        setFeedback({ type: "error", message: "Config not loaded yet. Please wait." });
        return;
      }
      setBusy(label);
      setFeedback(null);
      try {
        await callRpc("config.patch", {
          raw: JSON.stringify(patch),
          baseHash: snapshot.hash,
        });
        setFeedback({ type: "success", message: `${label}: success. Gateway restarting...` });
        mutateConfig();
        postAction?.();
      } catch (err) {
        setFeedback({
          type: "error",
          message: `${label}: ${err instanceof Error ? err.message : String(err)}`,
        });
      } finally {
        setBusy(null);
      }
    },
    [callRpc, configData, mutateConfig],
  );

  const selectedDef = PAIRING_CHANNELS.find((c) => c.id === selectedChannel)!;

  const handleAddUser = () => {
    const userId = userIdInput.trim();
    if (!userId) return;
    const validationError = selectedDef.validate(userId);
    if (validationError) {
      setFeedback({ type: "error", message: validationError });
      return;
    }
    const current = getCurrentAllowFrom(selectedChannel);
    if (current.includes(userId)) {
      setFeedback({ type: "error", message: `${userId} is already in the allowlist.` });
      return;
    }
    patchConfig(
      `Allow ${userId} on ${selectedChannel}`,
      { channels: { [selectedChannel]: { allowFrom: [...current, userId] } } },
      () => setUserIdInput(""),
    );
  };

  const handleRemoveUser = (channelId: string, userId: string) => {
    const current = getCurrentAllowFrom(channelId);
    patchConfig(
      `Remove ${userId} from ${channelId}`,
      { channels: { [channelId]: { allowFrom: current.filter((id) => id !== userId) } } },
    );
  };

  return (
    <div className="p-6 space-y-6 overflow-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Channel Access</h2>
          <p className="text-xs text-muted-foreground">
            Control who can message your agent on each channel.
          </p>
        </div>
        <Button variant="ghost" size="sm" onClick={() => mutateConfig()}>
          <RefreshCw className="h-3.5 w-3.5" />
        </Button>
      </div>

      {/* Feedback banner */}
      {feedback && (
        <div
          className={cn(
            "flex items-center gap-2 rounded-md border p-3 text-xs",
            feedback.type === "success"
              ? "border-emerald-500/30 bg-emerald-500/5 text-emerald-400"
              : "border-destructive/30 bg-destructive/5 text-destructive",
          )}
        >
          {feedback.type === "success" ? (
            <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
          ) : (
            <AlertCircle className="h-3.5 w-3.5 shrink-0" />
          )}
          <span className="flex-1">{feedback.message}</span>
          <button
            className="text-muted-foreground hover:text-foreground"
            onClick={() => setFeedback(null)}
          >
            dismiss
          </button>
        </div>
      )}

      {/* ── Add User to Allowlist ────────────────────── */}
      <section className="space-y-3">
        <div className="flex items-center gap-2">
          <UserPlus className="h-4 w-4 text-muted-foreground" />
          <h3 className="text-sm font-semibold">Add to Allowlist</h3>
        </div>
        <p className="text-xs text-muted-foreground">
          {selectedDef.help}
        </p>
        <div className="rounded-md border border-amber-500/20 bg-amber-500/5 p-2.5 text-xs text-amber-400">
          When someone messages your bot, they&apos;ll receive a pairing message containing
          both a <strong>pairing code</strong> and their <strong>numeric user ID</strong>.
          Enter the <strong>user ID</strong> below — not the pairing code.
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <select
            className="h-9 rounded-md border border-input bg-background px-2 text-xs outline-none focus:ring-1 focus:ring-ring"
            value={selectedChannel}
            onChange={(e) => setSelectedChannel(e.target.value)}
          >
            {PAIRING_CHANNELS.map((ch) => (
              <option key={ch.id} value={ch.id}>
                {ch.label}
              </option>
            ))}
          </select>
          <Input
            className="h-9 w-52 font-mono text-sm"
            placeholder={selectedDef.idPlaceholder}
            value={userIdInput}
            onChange={(e) => setUserIdInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleAddUser();
            }}
          />
          <Button
            size="sm"
            className="bg-emerald-600 hover:bg-emerald-700"
            disabled={!userIdInput.trim() || busy !== null}
            onClick={handleAddUser}
          >
            {busy?.startsWith("Allow") ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />
            ) : (
              <UserPlus className="h-3.5 w-3.5 mr-1" />
            )}
            Add
          </Button>
        </div>
      </section>

      {/* ── Per-Channel Status ───────────────────────── */}
      <section className="space-y-3">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-4 w-4 text-muted-foreground" />
          <h3 className="text-sm font-semibold">Channel Policies</h3>
        </div>

        <div className="space-y-3">
          {PAIRING_CHANNELS.map((ch) => {
            const policy = getCurrentDmPolicy(ch.id);
            const allowFrom = getCurrentAllowFrom(ch.id);
            const isConfigured = channels[ch.id] !== undefined;

            return (
              <div
                key={ch.id}
                className="rounded-lg border border-border p-3 space-y-2"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Radio className="h-3.5 w-3.5 text-muted-foreground" />
                    <span className="text-sm font-medium">{ch.label}</span>
                    {isConfigured && (
                      <span
                        className={cn(
                          "text-[10px] font-medium px-1.5 py-0.5 rounded",
                          policy === "open"
                            ? "bg-emerald-500/10 text-emerald-400"
                            : policy === "pairing"
                              ? "bg-amber-500/10 text-amber-400"
                              : policy === "disabled"
                                ? "bg-red-500/10 text-red-400"
                                : "bg-muted text-muted-foreground",
                        )}
                      >
                        {policy}
                      </span>
                    )}
                  </div>
                </div>

                {/* Allowlist */}
                {allowFrom.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 pt-1">
                    {allowFrom.map((userId) => (
                      <span
                        key={userId}
                        className="inline-flex items-center gap-1 text-[11px] font-mono bg-muted/30 px-2 py-0.5 rounded border border-border/50"
                      >
                        {userId}
                        <button
                          className="text-muted-foreground hover:text-destructive ml-0.5"
                          onClick={() => handleRemoveUser(ch.id, userId)}
                          disabled={busy !== null}
                        >
                          &times;
                        </button>
                      </span>
                    ))}
                  </div>
                )}

                {!isConfigured && (
                  <p className="text-[11px] text-muted-foreground/50">Not configured</p>
                )}
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
