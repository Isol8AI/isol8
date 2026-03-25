"use client";

import { useState, useCallback } from "react";
import {
  Loader2,
  RefreshCw,
  Radio,
  CheckCircle2,
  XCircle,
  MinusCircle,
  QrCode,
  LogOut,
  Scan,
  Link2,
  AlertCircle,
  Settings,
  Save,
  Eye,
  EyeOff,
} from "lucide-react";
import Image from "next/image";
import { useGatewayRpc, useGatewayRpcMutation } from "@/hooks/useGatewayRpc";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types — matching OpenClaw protocol
// ---------------------------------------------------------------------------

interface ChannelAccountSnapshot {
  accountId: string;
  name?: string | null;
  enabled?: boolean | null;
  configured?: boolean | null;
  linked?: boolean | null;
  running?: boolean | null;
  connected?: boolean | null;
  reconnectAttempts?: number | null;
  lastConnectedAt?: number | null;
  lastError?: string | null;
  lastStartAt?: number | null;
  lastStopAt?: number | null;
  lastInboundAt?: number | null;
  lastOutboundAt?: number | null;
  lastProbeAt?: number | null;
  mode?: string | null;
  dmPolicy?: string | null;
  tokenSource?: string | null;
  botTokenSource?: string | null;
  webhookUrl?: string | null;
  baseUrl?: string | null;
  [key: string]: unknown;
}

interface ChannelsStatusSnapshot {
  ts: number;
  channelOrder: string[];
  channelLabels: Record<string, string>;
  channelDetailLabels?: Record<string, string>;
  channels: Record<string, unknown>;
  channelAccounts: Record<string, ChannelAccountSnapshot[]>;
  channelDefaultAccountId: Record<string, string>;
}

interface ConfigSnapshot {
  path: string;
  exists: boolean;
  raw: string | null;
  config: Record<string, unknown>;
  hash?: string;
  valid: boolean;
  issues?: { path: string; message: string }[];
}

interface WebLoginResult {
  message?: string;
  qrDataUrl?: string;
  connected?: boolean;
}

// ---------------------------------------------------------------------------
// Channel config field definitions
// ---------------------------------------------------------------------------

interface ChannelField {
  key: string;
  label: string;
  placeholder: string;
  sensitive: boolean;
  help?: string;
}

const CHANNEL_CONFIG_FIELDS: Record<string, ChannelField[]> = {
  telegram: [
    {
      key: "botToken",
      label: "Bot Token",
      placeholder: "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
      sensitive: true,
      help: "Get from @BotFather on Telegram",
    },
  ],
  discord: [
    {
      key: "token",
      label: "Bot Token",
      placeholder: "your-discord-bot-token",
      sensitive: true,
      help: "From Discord Developer Portal → Bot → Token",
    },
  ],
  slack: [
    {
      key: "botToken",
      label: "Bot Token",
      placeholder: "xoxb-your-slack-bot-token",
      sensitive: true,
      help: "From Slack API → OAuth & Permissions → Bot User OAuth Token",
    },
    {
      key: "appToken",
      label: "App Token",
      placeholder: "xapp-your-slack-app-token",
      sensitive: true,
      help: "From Slack API → Basic Information → App-Level Tokens",
    },
  ],
  signal: [
    {
      key: "number",
      label: "Phone Number",
      placeholder: "+1234567890",
      sensitive: false,
      help: "Signal phone number in E.164 format",
    },
  ],
  googlechat: [
    {
      key: "credentials",
      label: "Service Account JSON",
      placeholder: '{"type":"service_account","project_id":"..."}',
      sensitive: true,
      help: "Google Cloud service account credentials JSON",
    },
  ],
  nostr: [
    {
      key: "privateKey",
      label: "Private Key (nsec)",
      placeholder: "nsec1...",
      sensitive: true,
    },
    {
      key: "relays",
      label: "Relay URLs",
      placeholder: "wss://relay.damus.io,wss://nos.lol",
      sensitive: false,
      help: "Comma-separated relay URLs",
    },
  ],
};

// ---------------------------------------------------------------------------
// Status constants
// ---------------------------------------------------------------------------

const DEFAULT_STATUS_FIELDS = [
  "configured",
  "linked",
  "running",
  "connected",
] as const;

const EXTENDED_STATUS_FIELDS = [
  ...DEFAULT_STATUS_FIELDS,
  "mode",
  "lastConnectedAt",
  "lastInboundAt",
  "lastOutboundAt",
  "lastError",
] as const;

const STATUS_LABELS: Record<string, string> = {
  configured: "Configured",
  linked: "Linked",
  running: "Running",
  connected: "Connected",
  enabled: "Enabled",
  mode: "Mode",
  dmPolicy: "DM policy",
  lastConnectedAt: "Last connected",
  lastInboundAt: "Last inbound",
  lastOutboundAt: "Last outbound",
  lastStartAt: "Last start",
  lastStopAt: "Last stop",
  lastProbeAt: "Last probe",
  lastError: "Last error",
  reconnectAttempts: "Reconnect attempts",
  tokenSource: "Token source",
  botTokenSource: "Bot token",
  webhookUrl: "Webhook URL",
  baseUrl: "Base URL",
};

const REDACTED_SENTINEL = "__OPENCLAW_REDACTED__";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatTimestamp(ts: number | null | undefined): string {
  if (!ts) return "n/a";
  const now = Date.now();
  const diffMs = now - ts;
  if (diffMs < 60_000) return "just now";
  if (diffMs < 3_600_000) return `${Math.floor(diffMs / 60_000)}m ago`;
  if (diffMs < 86_400_000) return `${Math.floor(diffMs / 3_600_000)}h ago`;
  return new Date(ts).toLocaleDateString();
}

function formatValue(
  key: string,
  value: unknown,
): { text: string; variant: "yes" | "no" | "muted" | "text" | "error" } {
  if (value === true) return { text: "Yes", variant: "yes" };
  if (value === false) return { text: "No", variant: "no" };
  if (value === null || value === undefined || value === "")
    return { text: "n/a", variant: "muted" };
  if (key === "lastError" && typeof value === "string")
    return { text: value, variant: "error" };
  if (key.startsWith("last") && typeof value === "number")
    return { text: formatTimestamp(value), variant: "text" };
  return { text: String(value), variant: "text" };
}

function isWhatsAppChannel(channelId: string): boolean {
  return channelId === "whatsapp" || channelId === "web";
}

/** Extract channel config from the full config object. */
function getChannelConfig(
  config: Record<string, unknown>,
  channelId: string,
): Record<string, unknown> {
  // Try channels.{id} first, then top-level {id}
  const channels = config.channels as Record<string, unknown> | undefined;
  const nested = channels?.[channelId];
  if (nested && typeof nested === "object") return nested as Record<string, unknown>;
  const topLevel = config[channelId];
  if (topLevel && typeof topLevel === "object") return topLevel as Record<string, unknown>;
  return {};
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function ChannelsPanel() {
  const { data, error, isLoading, mutate } =
    useGatewayRpc<ChannelsStatusSnapshot>("channels.status", { probe: false, timeoutMs: 8000 });
  const {
    data: configData,
    mutate: mutateConfig,
  } = useGatewayRpc<ConfigSnapshot>("config.get");
  const callRpc = useGatewayRpcMutation();

  // WhatsApp QR login state
  const [qrDataUrl, setQrDataUrl] = useState<string | null>(null);
  const [loginMessage, setLoginMessage] = useState<string | null>(null);
  const [actionBusy, setActionBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  // Per-channel allowlist input state
  const [allowlistInputs, setAllowlistInputs] = useState<Record<string, string>>({});

  // ---- Allowlist helpers ----

  const getChannelAllowFrom = (channelId: string): string[] => {
    const cfg = (configData as ConfigSnapshot | undefined)?.config ?? {};
    const ch = (cfg.channels as Record<string, Record<string, unknown>> | undefined)?.[channelId];
    if (!ch) return [];
    const af = ch.allowFrom;
    if (Array.isArray(af)) return af.map(String);
    return [];
  };

  const handleAddToAllowlist = async (channelId: string, userId: string) => {
    const snapshot = configData as ConfigSnapshot | undefined;
    if (!snapshot?.hash) return;
    const current = getChannelAllowFrom(channelId);
    if (current.includes(userId)) return;
    setActionBusy(`allow-${channelId}`);
    setActionError(null);
    try {
      await callRpc("config.patch", {
        raw: JSON.stringify({ channels: { [channelId]: { allowFrom: [...current, userId] } } }),
        baseHash: snapshot.hash,
      });
      mutateConfig();
      setAllowlistInputs((prev) => ({ ...prev, [channelId]: "" }));
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setActionBusy(null);
    }
  };

  const handleRemoveFromAllowlist = async (channelId: string, userId: string) => {
    const snapshot = configData as ConfigSnapshot | undefined;
    if (!snapshot?.hash) return;
    const current = getChannelAllowFrom(channelId);
    setActionBusy(`remove-${channelId}`);
    setActionError(null);
    try {
      await callRpc("config.patch", {
        raw: JSON.stringify({ channels: { [channelId]: { allowFrom: current.filter((id) => id !== userId) } } }),
        baseHash: snapshot.hash,
      });
      mutateConfig();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setActionBusy(null);
    }
  };

  // ---- WhatsApp actions ----

  const handleShowQr = async (force: boolean) => {
    const label = force ? "relink" : "qr";
    setActionBusy(label);
    setActionError(null);
    setLoginMessage(null);
    try {
      // Ensure the WhatsApp plugin is loaded. The plugin only loads when channels.whatsapp
      // has at least one key beyond "enabled". Old containers may only have { enabled: false },
      // which means the plugin is absent — patching dmPolicy triggers a gateway restart that
      // loads it (channels.whatsapp has no registered reload rule when the plugin is missing).
      const snapshot = configData as ConfigSnapshot | undefined;
      const waConfig = (snapshot?.config as Record<string, Record<string, unknown>> | undefined)
        ?.channels?.["whatsapp"] as Record<string, unknown> | undefined;
      const pluginLikelyLoaded = waConfig != null && Object.keys(waConfig).some((k) => k !== "enabled");

      if (!pluginLikelyLoaded && snapshot?.hash) {
        setLoginMessage("Preparing WhatsApp…");
        await callRpc("config.patch", {
          raw: JSON.stringify({ channels: { whatsapp: { dmPolicy: "pairing" } } }),
          baseHash: snapshot.hash,
        });
        setLoginMessage("Waiting for gateway…");
        const pollDeadline = Date.now() + 20_000;
        while (Date.now() < pollDeadline) {
          await new Promise((r) => setTimeout(r, 1500));
          try {
            await callRpc("config.get", undefined);
            break;
          } catch {
            // Still restarting
          }
        }
        setLoginMessage(null);
      }

      // 60s frontend timeout = 30s OpenClaw QR timeout + 30s buffer
      const res = await callRpc<WebLoginResult>("web.login.start", {
        force,
        timeoutMs: 30000,
      }, 60000);
      setQrDataUrl(res.qrDataUrl ?? null);
      setLoginMessage(res.message ?? null);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
      setQrDataUrl(null);
    } finally {
      setActionBusy(null);
    }
  };

  const attemptWhatsApp515Recovery = async (): Promise<boolean> => {
    setLoginMessage("Verifying WhatsApp pairing...");
    try {
      const status = await callRpc<{
        channelAccounts: Record<string, { linked?: boolean; configured?: boolean }[]>;
      }>("channels.status", {});
      const waAccounts = status?.channelAccounts?.whatsapp;
      const linked = waAccounts?.some((a) => a.linked || a.configured);

      if (!linked) {
        return false;
      }

      // Persist enabled + dmPolicy. channels.whatsapp is a noop prefix — no restart occurs.
      const snapshot = configData as ConfigSnapshot | undefined;
      if (snapshot?.hash) {
        try {
          await callRpc("config.patch", {
            raw: JSON.stringify({ channels: { whatsapp: { enabled: true, dmPolicy: "pairing" } } }),
            baseHash: snapshot.hash,
          });
        } catch {
          // best-effort
        }
      }

      setQrDataUrl(null);
      setLoginMessage("Connected!");
      mutate();
      return true;
    } catch {
      return false;
    }
  };

  const handleWaitForScan = async () => {
    setActionBusy("wait");
    setActionError(null);
    try {
      // 130s frontend timeout = 120s OpenClaw wait + 10s buffer
      const res = await callRpc<WebLoginResult>("web.login.wait", {
        timeoutMs: 120000,
      }, 130000);
      if (res.connected) {
        // Persist enabled=true so the channel auto-starts on next gateway restart.
        const snapshot = configData as ConfigSnapshot | undefined;
        if (snapshot?.hash) {
          try {
            await callRpc("config.patch", {
              raw: JSON.stringify({ channels: { whatsapp: { enabled: true, dmPolicy: "pairing" } } }),
              baseHash: snapshot.hash,
            });
          } catch {
            // best-effort
          }
        }
        setQrDataUrl(null);
        setLoginMessage("Connected!");
        mutate();
      } else {
        const is515 = res.message?.includes("515");
        if (is515) {
          const recovered = await attemptWhatsApp515Recovery();
          if (recovered) return;
        }
        setLoginMessage(res.message ?? null);
      }
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : String(err);
      const is515 = errMsg.includes("515");

      if (is515) {
        const recovered = await attemptWhatsApp515Recovery();
        if (recovered) return;
      }

      setActionError(errMsg);
    } finally {
      setActionBusy(null);
    }
  };

  const handleLogout = async (channel: string) => {
    setActionBusy(`logout-${channel}`);
    setActionError(null);
    try {
      await callRpc("channels.logout", { channel });
      if (isWhatsAppChannel(channel)) {
        setQrDataUrl(null);
        setLoginMessage("Logged out.");
      }
      mutate();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setActionBusy(null);
    }
  };

  const handleProbe = async () => {
    setActionBusy("probe");
    setActionError(null);
    try {
      await callRpc("channels.status", { probe: true, timeoutMs: 8000 });
      mutate();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setActionBusy(null);
    }
  };

  const handleSaveConfig = useCallback(
    async (channelId: string, values: Record<string, string>): Promise<void> => {
      const snapshot = configData as ConfigSnapshot | undefined;
      if (!snapshot?.hash) {
        setActionError("Config not loaded yet. Please wait and try again.");
        throw new Error("Config not loaded");
      }
      setActionBusy(`save-${channelId}`);
      setActionError(null);
      try {
        // Build partial config with only the changed channel values.
        // Using config.patch (not config.set) because config.get redacts
        // sensitive values — sending a full config back would overwrite
        // real tokens with __OPENCLAW_REDACTED__ sentinel strings.
        const channelPatch: Record<string, string> = {};
        for (const [key, value] of Object.entries(values)) {
          if (value !== REDACTED_SENTINEL && value !== "") {
            channelPatch[key] = value;
          }
        }

        if (Object.keys(channelPatch).length === 0) {
          return;
        }

        await callRpc("config.patch", {
          raw: JSON.stringify({ channels: { [channelId]: channelPatch } }),
          baseHash: snapshot.hash,
        });

        // Refresh config and status after save
        mutateConfig();
        // Wait a moment for gateway restart then refresh status
        setTimeout(() => mutate(), 3000);
      } catch (err) {
        setActionError(err instanceof Error ? err.message : String(err));
        throw err;
      } finally {
        setActionBusy(null);
      }
    },
    [callRpc, configData, mutate, mutateConfig],
  );

  // ---- Loading / Error states ----

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 space-y-3">
        <p className="text-sm text-destructive">{error.message}</p>
        <Button variant="outline" size="sm" onClick={() => mutate()}>
          <RefreshCw className="h-3.5 w-3.5 mr-1.5" /> Retry
        </Button>
      </div>
    );
  }

  // Parse responses
  const snapshot = data as ChannelsStatusSnapshot | null | undefined;
  const config = (configData as ConfigSnapshot | undefined)?.config ?? {};

  // Always show these three channels, even if the gateway doesn't report them
  const REQUIRED_CHANNELS = ["telegram", "whatsapp", "discord"];
  const DEFAULT_CHANNELS = [
    "telegram", "whatsapp", "discord", "googlechat",
    "slack", "signal", "imessage", "nostr",
  ];
  const DEFAULT_LABELS: Record<string, string> = {
    whatsapp: "WhatsApp", telegram: "Telegram", discord: "Discord",
    googlechat: "Google Chat", slack: "Slack", signal: "Signal",
    imessage: "iMessage", nostr: "Nostr",
  };
  const gatewayOrder = snapshot?.channelOrder?.length
    ? snapshot.channelOrder
    : DEFAULT_CHANNELS;
  // Merge: gateway-reported channels first, then ensure required channels are present
  const channelOrder = [
    ...gatewayOrder,
    ...REQUIRED_CHANNELS.filter((ch) => !gatewayOrder.includes(ch)),
  ];
  const channelLabels = { ...DEFAULT_LABELS, ...(snapshot?.channelLabels ?? {}) };
  const channelAccounts = snapshot?.channelAccounts ?? {};
  const channelDetailLabels = snapshot?.channelDetailLabels ?? {};

  return (
    <div className="p-6 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Channels</h2>
          <p className="text-xs text-muted-foreground">
            Connect communication channels to your agent.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleProbe}
            disabled={actionBusy !== null}
          >
            {actionBusy === "probe" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />
            ) : null}
            Probe All
          </Button>
          <Button variant="ghost" size="sm" onClick={() => mutate()}>
            <RefreshCw className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {/* Action feedback */}
      {actionError && (
        <div className="flex items-center gap-2 rounded-md border border-destructive/30 bg-destructive/5 p-3">
          <AlertCircle className="h-4 w-4 text-destructive shrink-0" />
          <p className="text-xs text-destructive">{actionError}</p>
          <button
            className="ml-auto text-xs text-muted-foreground hover:text-foreground"
            onClick={() => setActionError(null)}
          >
            dismiss
          </button>
        </div>
      )}

      {/* Channel cards */}
      <div className="space-y-4">
        {channelOrder.map((channelId) => {
          const accounts = channelAccounts[channelId] ?? [];
          const account = accounts[0];
          const label = channelLabels[channelId] ?? channelId;
          const detail = channelDetailLabels[channelId];
          const isWa = isWhatsAppChannel(channelId);
          const channelConf = getChannelConfig(config, channelId);
          const configFields = CHANNEL_CONFIG_FIELDS[channelId];

          const allowFrom = getChannelAllowFrom(channelId);
          const dmPolicy = account?.dmPolicy ?? null;

          return (
            <ChannelCard
              key={channelId}
              channelId={channelId}
              label={label}
              detail={detail}
              account={account}
              isWhatsApp={isWa}
              qrDataUrl={isWa ? qrDataUrl : null}
              loginMessage={isWa ? loginMessage : null}
              actionBusy={actionBusy}
              configFields={configFields}
              channelConfig={channelConf}
              allowFrom={allowFrom}
              dmPolicy={dmPolicy}
              allowlistInput={allowlistInputs[channelId] ?? ""}
              onAllowlistInputChange={(val) => setAllowlistInputs((prev) => ({ ...prev, [channelId]: val }))}
              onAddToAllowlist={(userId) => handleAddToAllowlist(channelId, userId)}
              onRemoveFromAllowlist={(userId) => handleRemoveFromAllowlist(channelId, userId)}
              onShowQr={() => handleShowQr(false)}
              onRelink={() => handleShowQr(true)}
              onWaitForScan={handleWaitForScan}
              onLogout={() => handleLogout(channelId)}
              onSaveConfig={(values) => handleSaveConfig(channelId, values)}
            />
          );
        })}
      </div>

      {/* Raw snapshot for debugging */}
      {snapshot && (
        <details className="text-xs">
          <summary className="text-muted-foreground cursor-pointer hover:text-foreground">
            Raw gateway response
          </summary>
          <pre className="mt-2 p-3 rounded-md bg-muted/30 border border-border/40 overflow-auto max-h-60 text-[10px] leading-tight">
            {JSON.stringify(snapshot, null, 2)}
          </pre>
        </details>
      )}
      {!snapshot && !isLoading && !error && (
        <p className="text-xs text-muted-foreground">
          No response from gateway. WebSocket may not be connected.
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Channel card
// ---------------------------------------------------------------------------

function ChannelCard({
  channelId,
  label,
  detail,
  account,
  isWhatsApp,
  qrDataUrl,
  loginMessage,
  actionBusy,
  configFields,
  channelConfig,
  allowFrom,
  dmPolicy,
  allowlistInput,
  onAllowlistInputChange,
  onAddToAllowlist,
  onRemoveFromAllowlist,
  onShowQr,
  onRelink,
  onWaitForScan,
  onLogout,
  onSaveConfig,
}: {
  channelId: string;
  label: string;
  detail?: string;
  account: ChannelAccountSnapshot | undefined;
  isWhatsApp: boolean;
  qrDataUrl: string | null;
  loginMessage: string | null;
  actionBusy: string | null;
  configFields: ChannelField[] | undefined;
  channelConfig: Record<string, unknown>;
  allowFrom: string[];
  dmPolicy: string | null;
  allowlistInput: string;
  onAllowlistInputChange: (val: string) => void;
  onAddToAllowlist: (userId: string) => void;
  onRemoveFromAllowlist: (userId: string) => void;
  onShowQr: () => void;
  onRelink: () => void;
  onWaitForScan: () => void;
  onLogout: () => void;
  onSaveConfig: (values: Record<string, string>) => Promise<void>;
}) {
  const busy = actionBusy !== null;
  const [showConfig, setShowConfig] = useState(false);

  // Pick status fields to display
  const fields = account
    ? (EXTENDED_STATUS_FIELDS as readonly string[]).filter(
        (f) => account[f] !== undefined && account[f] !== null,
      )
    : [];
  const coreFields = (DEFAULT_STATUS_FIELDS as readonly string[]).filter(
    (f) => !fields.includes(f),
  );

  return (
    <div className="rounded-lg border border-border overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between p-4 pb-2">
        <div className="flex items-center gap-2">
          <Radio className="h-4 w-4 text-muted-foreground" />
          <div>
            <h3 className="text-sm font-semibold">{label}</h3>
            {detail && (
              <p className="text-xs text-muted-foreground">{detail}</p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {account?.connected && (
            <span className="inline-flex items-center gap-1 text-xs text-green-600 font-medium">
              <CheckCircle2 className="h-3 w-3" />
              Connected
            </span>
          )}
          {configFields && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowConfig(!showConfig)}
              className="h-7 px-2"
            >
              <Settings className="h-3.5 w-3.5" />
            </Button>
          )}
        </div>
      </div>

      {/* Status grid */}
      {account ? (
        <div className="px-4 pb-3">
          <div className="rounded-md border border-border/60 bg-muted/10 p-3">
            <div className="grid grid-cols-2 md:grid-cols-3 gap-x-4 gap-y-1.5">
              {[...coreFields, ...fields].map((field) => {
                const { text, variant } = formatValue(field, account[field]);
                return (
                  <div key={field} className="flex items-center gap-1.5 text-xs">
                    <span className="text-muted-foreground">
                      {STATUS_LABELS[field] || field}:
                    </span>
                    <StatusBadge text={text} variant={variant} />
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      ) : (
        <div className="px-4 pb-3">
          <p className="text-xs text-muted-foreground">
            Not configured.{" "}
            {configFields
              ? "Click the gear icon to set up this channel."
              : isWhatsApp
                ? "Use Show QR to connect."
                : "No configuration fields available for this channel."}
          </p>
        </div>
      )}

      {/* Config form */}
      {showConfig && configFields && (
        <ChannelConfigForm
          channelId={channelId}
          fields={configFields}
          currentConfig={channelConfig}
          busy={busy}
          onSave={onSaveConfig}
        />
      )}

      {/* WhatsApp QR code display */}
      {isWhatsApp && qrDataUrl && (
        <div className="px-4 pb-3">
          <div className="rounded-md border border-border/60 bg-background p-4 flex flex-col items-center gap-3">
            <Image
              src={qrDataUrl}
              alt="WhatsApp QR Code"
              width={192}
              height={192}
              unoptimized
              className="rounded"
            />
            <p className="text-xs text-muted-foreground text-center">
              Scan this QR code with WhatsApp on your phone
            </p>
          </div>
        </div>
      )}

      {/* WhatsApp login message */}
      {isWhatsApp && loginMessage && (
        <div className="px-4 pb-3">
          <p className="text-xs text-muted-foreground bg-muted/20 rounded p-2">
            {loginMessage}
          </p>
        </div>
      )}

      {/* Action buttons */}
      <div className="flex flex-wrap items-center gap-2 px-4 pb-4">
        {isWhatsApp ? (
          <>
            <Button variant="outline" size="sm" onClick={onShowQr} disabled={busy}>
              {actionBusy === "qr" ? (
                <Loader2 className="h-3 w-3 animate-spin mr-1" />
              ) : (
                <QrCode className="h-3 w-3 mr-1" />
              )}
              Show QR
            </Button>
            <Button variant="outline" size="sm" onClick={onRelink} disabled={busy}>
              {actionBusy === "relink" ? (
                <Loader2 className="h-3 w-3 animate-spin mr-1" />
              ) : (
                <Link2 className="h-3 w-3 mr-1" />
              )}
              Relink
            </Button>
            {qrDataUrl && (
              <Button variant="outline" size="sm" onClick={onWaitForScan} disabled={busy}>
                {actionBusy === "wait" ? (
                  <Loader2 className="h-3 w-3 animate-spin mr-1" />
                ) : (
                  <Scan className="h-3 w-3 mr-1" />
                )}
                Wait for scan
              </Button>
            )}
            <Button variant="outline" size="sm" onClick={onLogout} disabled={busy}>
              {actionBusy?.startsWith("logout") ? (
                <Loader2 className="h-3 w-3 animate-spin mr-1" />
              ) : (
                <LogOut className="h-3 w-3 mr-1" />
              )}
              Logout
            </Button>
          </>
        ) : (
          <Button variant="outline" size="sm" onClick={onLogout} disabled={busy}>
            {actionBusy?.startsWith("logout") ? (
              <Loader2 className="h-3 w-3 animate-spin mr-1" />
            ) : (
              <LogOut className="h-3 w-3 mr-1" />
            )}
            Logout
          </Button>
        )}
      </div>

      {/* Allowlist section */}
      <div className="px-4 pb-4 space-y-2">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-muted-foreground">Allowed Users</span>
          {dmPolicy && (
            <span className={cn(
              "text-[10px] font-medium px-1.5 py-0.5 rounded",
              dmPolicy === "open" ? "bg-emerald-500/10 text-emerald-400"
                : dmPolicy === "pairing" ? "bg-amber-500/10 text-amber-400"
                : "bg-muted text-muted-foreground"
            )}>
              {dmPolicy}
            </span>
          )}
        </div>
        {allowFrom.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {allowFrom.map((userId) => (
              <span key={userId} className="inline-flex items-center gap-1 text-[11px] font-mono bg-muted/30 px-2 py-0.5 rounded border border-border/50">
                {userId}
                <button className="text-muted-foreground hover:text-destructive ml-0.5" onClick={() => onRemoveFromAllowlist(userId)} disabled={busy}>&times;</button>
              </span>
            ))}
          </div>
        )}
        <div className="flex items-center gap-2">
          <input
            type="text"
            placeholder="User ID"
            value={allowlistInput}
            onChange={(e) => onAllowlistInputChange(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && allowlistInput.trim()) onAddToAllowlist(allowlistInput.trim()); }}
            className="w-40 rounded-md border border-border bg-background px-2 py-1 text-xs font-mono placeholder:text-muted-foreground/40 focus:outline-none focus:ring-1 focus:ring-ring"
          />
          <Button variant="outline" size="sm" onClick={() => { if (allowlistInput.trim()) onAddToAllowlist(allowlistInput.trim()); }} disabled={!allowlistInput.trim() || busy}>
            Add
          </Button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Channel config form
// ---------------------------------------------------------------------------

function ChannelConfigForm({
  fields,
  currentConfig,
  busy,
  onSave,
}: {
  channelId: string;
  fields: ChannelField[];
  currentConfig: Record<string, unknown>;
  busy: boolean;
  onSave: (values: Record<string, string>) => Promise<void>;
}) {
  // Build initial values from current config (computed once via lazy initializer)
  const [initialSnapshot] = useState(() => {
    const init: Record<string, string> = {};
    for (const field of fields) {
      const val = currentConfig[field.key];
      init[field.key] = typeof val === "string" ? val : val ? String(val) : "";
    }
    return init;
  });

  const [values, setValues] = useState<Record<string, string>>(
    () => ({ ...initialSnapshot }),
  );
  const [showSecrets, setShowSecrets] = useState<Record<string, boolean>>({});
  const [saved, setSaved] = useState(false);

  const handleChange = (key: string, value: string) => {
    setValues((prev) => ({ ...prev, [key]: value }));
    setSaved(false);
  };

  const handleSave = async () => {
    try {
      await onSave(values);
      setSaved(true);
    } catch {
      // Error is displayed by parent via actionError
      setSaved(false);
    }
  };

  const hasChanges = fields.some((f) => {
    const current = values[f.key] ?? "";
    const original = initialSnapshot[f.key] ?? "";
    return current !== original && current !== REDACTED_SENTINEL;
  });

  return (
    <div className="px-4 pb-3">
      <div className="rounded-md border border-border/60 bg-muted/5 p-4 space-y-3">
        <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
          Configuration
        </h4>

        {fields.map((field) => {
          const isRedacted = values[field.key] === REDACTED_SENTINEL;
          const isSecret = field.sensitive;
          const showing = showSecrets[field.key] ?? false;

          return (
            <div key={field.key} className="space-y-1">
              <label className="text-xs font-medium text-foreground">
                {field.label}
              </label>
              <div className="relative">
                <input
                  type={isSecret && !showing ? "password" : "text"}
                  value={isRedacted ? "••••••••" : values[field.key] ?? ""}
                  placeholder={field.placeholder}
                  onChange={(e) => handleChange(field.key, e.target.value)}
                  onFocus={() => {
                    // Clear redacted sentinel on focus so user can type new value
                    if (isRedacted) {
                      handleChange(field.key, "");
                    }
                  }}
                  disabled={busy}
                  className="w-full rounded-md border border-border bg-background px-3 py-1.5 text-xs font-mono placeholder:text-muted-foreground/40 focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-50"
                />
                {isSecret && (
                  <button
                    type="button"
                    onClick={() =>
                      setShowSecrets((prev) => ({
                        ...prev,
                        [field.key]: !prev[field.key],
                      }))
                    }
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                  >
                    {showing ? (
                      <EyeOff className="h-3 w-3" />
                    ) : (
                      <Eye className="h-3 w-3" />
                    )}
                  </button>
                )}
              </div>
              {field.help && (
                <p className="text-[10px] text-muted-foreground">{field.help}</p>
              )}
            </div>
          );
        })}

        <div className="flex items-center gap-2 pt-1">
          <Button
            variant="default"
            size="sm"
            onClick={handleSave}
            disabled={busy || !hasChanges}
          >
            {busy ? (
              <Loader2 className="h-3 w-3 animate-spin mr-1" />
            ) : (
              <Save className="h-3 w-3 mr-1" />
            )}
            Save
          </Button>
          {saved && !busy && (
            <span className="text-xs text-green-600">
              Saved! Gateway restarting...
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------

function StatusBadge({
  text,
  variant,
}: {
  text: string;
  variant: "yes" | "no" | "muted" | "text" | "error";
}) {
  if (variant === "yes") {
    return (
      <span className="inline-flex items-center gap-0.5 text-green-600">
        <CheckCircle2 className="h-3 w-3" />
        <span className="font-medium">{text}</span>
      </span>
    );
  }
  if (variant === "no") {
    return (
      <span className="inline-flex items-center gap-0.5 text-red-500">
        <XCircle className="h-3 w-3" />
        <span className="font-medium">{text}</span>
      </span>
    );
  }
  if (variant === "error") {
    return (
      <span className="text-red-500 font-medium truncate max-w-[200px]">
        {text}
      </span>
    );
  }
  if (variant === "muted") {
    return (
      <span className="inline-flex items-center gap-0.5 text-muted-foreground/50">
        <MinusCircle className="h-3 w-3" />
        <span>{text}</span>
      </span>
    );
  }
  return <span className="font-medium truncate max-w-[140px]">{text}</span>;
}
