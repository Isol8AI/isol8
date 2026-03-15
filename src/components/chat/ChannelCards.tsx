"use client";

import { useState, useCallback } from "react";
import {
  Loader2,
  CheckCircle,
  Eye,
  EyeOff,
  QrCode,
  Scan,
  LogOut,
  RefreshCw,
  AlertTriangle,
  ArrowLeft,
  MessageCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useGatewayRpc, useGatewayRpcMutation } from "@/hooks/useGatewayRpc";

const DISMISS_KEY = "isol8:channel-cards-dismissed";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ChannelDef {
  id: string;
  label: string;
  description: string;
  icon: string;
  fields: { key: string; label: string; placeholder: string; sensitive: boolean; help: string }[];
  instructions: string[];
}

interface ConfigSnapshot {
  path: string;
  exists: boolean;
  raw: string | null;
  config: Record<string, unknown>;
  hash?: string;
  valid: boolean;
}

interface WebLoginResult {
  message?: string;
  qrDataUrl?: string;
  connected?: boolean;
}

// ---------------------------------------------------------------------------
// Channel definitions
// ---------------------------------------------------------------------------

const CHANNELS: ChannelDef[] = [
  {
    id: "telegram",
    label: "Telegram",
    description: "Chat via Telegram bot",
    icon: "💬",
    instructions: [
      "Open Telegram and search for @BotFather",
      "Send /newbot and follow the prompts to create a bot",
      "Copy the bot token BotFather gives you",
      "Message @RawDataBot on Telegram to get your numerical user ID",
      "Paste the token and user ID below and click Connect",
    ],
    fields: [
      {
        key: "botToken",
        label: "Bot Token",
        placeholder: "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        sensitive: true,
        help: "Get from @BotFather on Telegram",
      },
      {
        key: "userId",
        label: "Your Telegram User ID",
        placeholder: "7895038573",
        sensitive: false,
        help: "Message @RawDataBot on Telegram — your ID is in the response",
      },
    ],
  },
  {
    id: "discord",
    label: "Discord",
    description: "Chat via Discord bot",
    icon: "🎮",
    instructions: [
      "Go to discord.com/developers and create a new Application",
      "Under Bot, click Reset Token and copy it",
      "Under OAuth2, generate an invite URL with bot + message permissions",
      "Invite the bot to your server, then paste the token below",
    ],
    fields: [
      {
        key: "token",
        label: "Bot Token",
        placeholder: "your-discord-bot-token",
        sensitive: true,
        help: "From Discord Developer Portal > Bot > Token",
      },
      {
        key: "userId",
        label: "Your Discord User ID",
        placeholder: "123456789012345678",
        sensitive: false,
        help: "Enable Developer Mode, then right-click your name to copy ID",
      },
    ],
  },
  {
    id: "whatsapp",
    label: "WhatsApp",
    description: "Chat via WhatsApp",
    icon: "📱",
    instructions: [
      "Click Show QR Code below",
      "Open WhatsApp on your phone",
      "Go to Settings > Linked Devices > Link a Device",
      "Scan the QR code with your phone camera",
    ],
    fields: [],
  },
];

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface ChannelCardsProps {
  onDismiss: () => void;
}

export function ChannelCards({ onDismiss }: ChannelCardsProps) {
  const [expandedChannel, setExpandedChannel] = useState<string | null>(null);
  const [connectedChannels, setConnectedChannels] = useState<Set<string>>(new Set());
  const [fieldValues, setFieldValues] = useState<Record<string, Record<string, string>>>({});
  const [showSecrets, setShowSecrets] = useState<Record<string, boolean>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState<string | null>(null);
  const [animatingOut, setAnimatingOut] = useState(false);

  // WhatsApp state
  const [qrDataUrl, setQrDataUrl] = useState<string | null>(null);
  const [waMessage, setWaMessage] = useState<string | null>(null);
  const [waBusy, setWaBusy] = useState<string | null>(null);
  const [waLoginFailed, setWaLoginFailed] = useState(false);

  const { data: configData } = useGatewayRpc<ConfigSnapshot>("config.get");
  const callRpc = useGatewayRpcMutation();

  // ---- Dismiss with animation ----
  const handleDismiss = useCallback(() => {
    setAnimatingOut(true);
    localStorage.setItem(DISMISS_KEY, "true");
    setTimeout(() => onDismiss(), 300);
  }, [onDismiss]);

  // ---- Field helpers ----
  const getFieldValue = useCallback(
    (channelId: string, fieldKey: string): string => {
      return fieldValues[channelId]?.[fieldKey] ?? "";
    },
    [fieldValues],
  );

  const setFieldValue = (channelId: string, fieldKey: string, value: string) => {
    setFieldValues((prev) => ({
      ...prev,
      [channelId]: { ...prev[channelId], [fieldKey]: value },
    }));
    setErrors((prev) => {
      const next = { ...prev };
      delete next[channelId];
      return next;
    });
  };

  // ---- Connect channel (Telegram/Discord) ----
  const handleConnect = useCallback(
    async (channel: ChannelDef) => {
      const snapshot = configData as ConfigSnapshot | undefined;
      if (!snapshot?.hash) {
        setErrors((prev) => ({ ...prev, [channel.id]: "Config not loaded yet. Please wait." }));
        return;
      }

      for (const field of channel.fields) {
        if (field.key === "userId") continue;
        const val = getFieldValue(channel.id, field.key);
        if (!val.trim()) {
          setErrors((prev) => ({ ...prev, [channel.id]: `${field.label} is required` }));
          return;
        }
      }

      setSaving(channel.id);
      setErrors((prev) => {
        const next = { ...prev };
        delete next[channel.id];
        return next;
      });

      try {
        const channelPatch: Record<string, unknown> = {};
        const userId = getFieldValue(channel.id, "userId");
        for (const field of channel.fields) {
          if (field.key === "userId") continue;
          channelPatch[field.key] = getFieldValue(channel.id, field.key);
        }
        if (userId.trim()) {
          channelPatch.allowFrom = [userId.trim()];
        }

        await callRpc("config.patch", {
          raw: JSON.stringify({ channels: { [channel.id]: channelPatch } }),
          baseHash: snapshot.hash,
        });

        await new Promise((r) => setTimeout(r, 3000));
        const status = await callRpc<{
          channelAccounts: Record<string, { connected?: boolean; configured?: boolean; running?: boolean }[]>;
        }>("channels.status", { probe: true, timeoutMs: 8000 });

        const accounts = status?.channelAccounts?.[channel.id];
        const account = accounts?.[0];
        const isConnected = account?.configured === true || account?.running === true;

        if (isConnected) {
          setConnectedChannels((prev) => new Set([...prev, channel.id]));
          setExpandedChannel(null);
        } else {
          setErrors((prev) => ({
            ...prev,
            [channel.id]: "Could not verify connection. Check your token and try again.",
          }));
        }
      } catch (err) {
        setErrors((prev) => ({
          ...prev,
          [channel.id]: err instanceof Error ? err.message : String(err),
        }));
      } finally {
        setSaving(null);
      }
    },
    [callRpc, configData, getFieldValue],
  );

  // ---- WhatsApp QR flow ----
  const handleWhatsAppQr = async () => {
    setWaBusy("qr");
    setWaLoginFailed(false);
    setErrors((prev) => {
      const next = { ...prev };
      delete next["whatsapp"];
      return next;
    });
    try {
      const res = await callRpc<WebLoginResult>("web.login.start", {
        force: waLoginFailed,
        timeoutMs: 30000,
      });
      setQrDataUrl(res.qrDataUrl ?? null);
      setWaMessage(res.message ?? null);
    } catch (err) {
      setErrors((prev) => ({
        ...prev,
        whatsapp: err instanceof Error ? err.message : String(err),
      }));
      setQrDataUrl(null);
    } finally {
      setWaBusy(null);
    }
  };

  const handleWhatsAppWait = async () => {
    setWaBusy("wait");
    setErrors((prev) => {
      const next = { ...prev };
      delete next["whatsapp"];
      return next;
    });
    try {
      const res = await callRpc<WebLoginResult>("web.login.wait", {
        timeoutMs: 120000,
      });
      if (res.connected) {
        setQrDataUrl(null);
        setWaMessage(null);
        setWaLoginFailed(false);
        setConnectedChannels((prev) => new Set([...prev, "whatsapp"]));
        setExpandedChannel(null);
      } else {
        const is515 = res.message?.includes("515");
        if (is515) {
          const recovered = await attemptWhatsApp515Recovery();
          if (recovered) return;
        }
        setWaMessage(res.message ?? "Waiting timed out. Try again.");
      }
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : String(err);
      const is515 = errMsg.includes("515");

      if (is515) {
        const recovered = await attemptWhatsApp515Recovery();
        if (recovered) return;
      }

      setWaLoginFailed(true);
      setQrDataUrl(null);
      setWaMessage(null);
      if (!is515) {
        try {
          await callRpc("channels.logout", { channel: "whatsapp" });
        } catch {
          // best-effort
        }
      }
      setErrors((prev) => ({
        ...prev,
        whatsapp: errMsg,
      }));
    } finally {
      setWaBusy(null);
    }
  };

  const attemptWhatsApp515Recovery = async (): Promise<boolean> => {
    setWaMessage("Verifying WhatsApp pairing...");
    try {
      await new Promise((r) => setTimeout(r, 3000));
      const status = await callRpc<{
        channelAccounts: Record<string, { linked?: boolean; configured?: boolean }[]>;
      }>("channels.status", {});
      const waAccounts = status?.channelAccounts?.whatsapp;
      const linked = waAccounts?.some((a) => a.linked || a.configured);

      if (!linked) return false;

      const snapshot = configData as ConfigSnapshot | undefined;
      if (snapshot?.hash) {
        await callRpc("config.patch", {
          raw: JSON.stringify({ channels: { whatsapp: { dmPolicy: "pairing" } } }),
          baseHash: snapshot.hash,
        });
        await new Promise((r) => setTimeout(r, 4000));
      }

      setQrDataUrl(null);
      setWaMessage(null);
      setWaLoginFailed(false);
      setConnectedChannels((prev) => new Set([...prev, "whatsapp"]));
      setExpandedChannel(null);
      return true;
    } catch {
      return false;
    }
  };

  const handleWhatsAppLogout = async () => {
    setWaBusy("logout");
    setErrors((prev) => {
      const next = { ...prev };
      delete next["whatsapp"];
      return next;
    });
    try {
      await callRpc("channels.logout", { channel: "whatsapp" });
      setQrDataUrl(null);
      setWaMessage("Session cleared. You can pair again.");
      setWaLoginFailed(false);
      setConnectedChannels((prev) => {
        const next = new Set(prev);
        next.delete("whatsapp");
        return next;
      });
    } catch (err) {
      setErrors((prev) => ({
        ...prev,
        whatsapp: err instanceof Error ? err.message : String(err),
      }));
    } finally {
      setWaBusy(null);
    }
  };

  // ---- Render ----
  const isExpanded = expandedChannel !== null;
  const expandedDef = CHANNELS.find((c) => c.id === expandedChannel);

  return (
    <div
      className={`flex flex-col items-center justify-center w-full max-w-3xl mx-auto px-4 transition-all duration-300 ${
        animatingOut ? "opacity-0 translate-y-4" : "opacity-100 translate-y-0"
      }`}
    >
      <div className="text-center mb-8">
        <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-white/5 mb-4">
          <MessageCircle className="h-6 w-6 text-white/60" />
        </div>
        <h2 className="text-xl font-semibold text-foreground mb-1">Connect a channel</h2>
        <p className="text-sm text-muted-foreground">
          Chat with your agent on your favorite platform
        </p>
      </div>

      {/* Cards grid or expanded view */}
      {!isExpanded ? (
        <div className="grid grid-cols-3 gap-4 w-full max-w-lg">
          {CHANNELS.map((channel) => {
            const isConnected = connectedChannels.has(channel.id);
            return (
              <button
                key={channel.id}
                type="button"
                onClick={() => !isConnected && setExpandedChannel(channel.id)}
                disabled={isConnected}
                className={`group relative flex flex-col items-center gap-3 rounded-xl border p-6 text-center transition-all duration-200 ${
                  isConnected
                    ? "border-green-500/30 bg-green-500/5 cursor-default"
                    : "border-border hover:border-white/20 hover:bg-white/5 cursor-pointer"
                }`}
              >
                <span className="text-3xl">{channel.icon}</span>
                <div>
                  <p className="text-sm font-medium text-foreground">{channel.label}</p>
                  <p className="text-xs text-muted-foreground mt-0.5">{channel.description}</p>
                </div>
                {isConnected && (
                  <span className="inline-flex items-center gap-1 text-xs text-green-500 font-medium">
                    <CheckCircle className="h-3 w-3" />
                    Connected
                  </span>
                )}
              </button>
            );
          })}
        </div>
      ) : expandedDef ? (
        <div className="w-full max-w-lg rounded-xl border border-border bg-card/30 overflow-hidden animate-in fade-in slide-in-from-bottom-2 duration-200">
          {/* Header */}
          <div className="flex items-center gap-3 p-4 border-b border-border">
            <button
              type="button"
              onClick={() => setExpandedChannel(null)}
              className="rounded-md p-1 text-muted-foreground hover:text-foreground hover:bg-white/5 transition-colors"
            >
              <ArrowLeft className="h-4 w-4" />
            </button>
            <span className="text-xl">{expandedDef.icon}</span>
            <h3 className="text-sm font-semibold">{expandedDef.label}</h3>
            {connectedChannels.has(expandedDef.id) && (
              <span className="ml-auto inline-flex items-center gap-1 text-xs text-green-500 font-medium">
                <CheckCircle className="h-3 w-3" />
                Connected
              </span>
            )}
          </div>

          {/* Body */}
          <div className="p-4 space-y-4">
            {/* Instructions */}
            <div className="space-y-2">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Steps</p>
              <ol className="space-y-2">
                {expandedDef.instructions.map((step, i) => (
                  <li key={i} className="flex gap-2.5 text-sm text-white/80">
                    <span className="flex-shrink-0 w-5 h-5 rounded-full bg-white/10 text-white/50 text-xs flex items-center justify-center font-medium">
                      {i + 1}
                    </span>
                    <span>{step}</span>
                  </li>
                ))}
              </ol>
            </div>

            {/* Credential fields (Telegram/Discord) */}
            {expandedDef.fields.length > 0 && (
              <div className="space-y-3 pt-2 border-t border-border">
                {expandedDef.fields.map((field) => (
                  <div key={field.key} className="space-y-1">
                    <label className="text-xs font-medium">{field.label}</label>
                    <div className="relative">
                      <input
                        type={field.sensitive && !showSecrets[`${expandedDef.id}.${field.key}`] ? "password" : "text"}
                        value={getFieldValue(expandedDef.id, field.key)}
                        placeholder={field.placeholder}
                        onChange={(e) => setFieldValue(expandedDef.id, field.key, e.target.value)}
                        disabled={saving === expandedDef.id}
                        className="w-full rounded-md border border-border bg-background px-3 py-1.5 text-xs font-mono placeholder:text-muted-foreground/40 focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-50"
                      />
                      {field.sensitive && (
                        <button
                          type="button"
                          onClick={() =>
                            setShowSecrets((prev) => ({
                              ...prev,
                              [`${expandedDef.id}.${field.key}`]: !prev[`${expandedDef.id}.${field.key}`],
                            }))
                          }
                          className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                        >
                          {showSecrets[`${expandedDef.id}.${field.key}`] ? (
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
                ))}
              </div>
            )}

            {/* WhatsApp QR flow */}
            {expandedDef.id === "whatsapp" && (
              <div className="space-y-3 pt-2 border-t border-border">
                {waLoginFailed && (
                  <div className="flex items-start gap-2 rounded-md border border-yellow-500/30 bg-yellow-500/10 p-2.5">
                    <AlertTriangle className="h-3.5 w-3.5 text-yellow-500 mt-0.5 shrink-0" />
                    <div className="text-xs text-yellow-200 space-y-1">
                      <p>Previous login failed. Session has been cleared.</p>
                      <p className="text-yellow-200/60">Click &ldquo;Show QR Code&rdquo; to try again.</p>
                    </div>
                  </div>
                )}

                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleWhatsAppQr}
                    disabled={waBusy !== null}
                  >
                    {waBusy === "qr" ? (
                      <Loader2 className="h-3 w-3 animate-spin mr-1" />
                    ) : waLoginFailed ? (
                      <RefreshCw className="h-3 w-3 mr-1" />
                    ) : (
                      <QrCode className="h-3 w-3 mr-1" />
                    )}
                    {waLoginFailed ? "Retry QR Code" : "Show QR Code"}
                  </Button>
                  {qrDataUrl && (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={handleWhatsAppWait}
                      disabled={waBusy !== null}
                    >
                      {waBusy === "wait" ? (
                        <Loader2 className="h-3 w-3 animate-spin mr-1" />
                      ) : (
                        <Scan className="h-3 w-3 mr-1" />
                      )}
                      I scanned it
                    </Button>
                  )}
                  {(qrDataUrl || waLoginFailed || errors["whatsapp"]) && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={handleWhatsAppLogout}
                      disabled={waBusy !== null}
                      className="text-muted-foreground hover:text-red-400"
                    >
                      {waBusy === "logout" ? (
                        <Loader2 className="h-3 w-3 animate-spin mr-1" />
                      ) : (
                        <LogOut className="h-3 w-3 mr-1" />
                      )}
                      Clear session
                    </Button>
                  )}
                </div>
                {qrDataUrl && (
                  <div className="flex justify-center">
                    <img
                      src={qrDataUrl}
                      alt="WhatsApp QR Code"
                      className="w-48 h-48 rounded border border-border"
                    />
                  </div>
                )}
                {waMessage && (
                  <p className="text-xs text-muted-foreground bg-muted/20 rounded p-2">
                    {waMessage}
                  </p>
                )}
              </div>
            )}

            {/* Error */}
            {errors[expandedDef.id] && (
              <p className="text-xs text-red-500">{errors[expandedDef.id]}</p>
            )}

            {/* Connect button (Telegram/Discord only) */}
            {expandedDef.id !== "whatsapp" && (
              <Button
                size="sm"
                onClick={() => handleConnect(expandedDef)}
                disabled={saving === expandedDef.id}
                className="w-full"
              >
                {saving === expandedDef.id ? (
                  <Loader2 className="h-3 w-3 animate-spin mr-1" />
                ) : null}
                Connect {expandedDef.label}
              </Button>
            )}
          </div>
        </div>
      ) : null}

      {/* Maybe later */}
      <button
        type="button"
        onClick={handleDismiss}
        className="mt-6 text-sm text-muted-foreground hover:text-foreground transition-colors"
      >
        Maybe later
      </button>
    </div>
  );
}

/** Check if channel cards have been dismissed (for use in parent components) */
export function isChannelCardsDismissed(): boolean {
  if (typeof window === "undefined") return true;
  return localStorage.getItem(DISMISS_KEY) === "true";
}
