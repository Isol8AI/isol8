"use client";

import { useState, useCallback } from "react";
import {
  Loader2,
  CheckCircle,
  ChevronDown,
  ChevronRight,
  Eye,
  EyeOff,
  QrCode,
  Scan,
  LogOut,
  RefreshCw,
  AlertTriangle,
} from "lucide-react";
import Image from "next/image";
import { Button } from "@/components/ui/button";
import { useGatewayRpc, useGatewayRpcMutation } from "@/hooks/useGatewayRpc";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ChannelDef {
  id: string;
  label: string;
  fields: { key: string; label: string; placeholder: string; sensitive: boolean; help: string }[];
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
// Channel definitions — only Telegram, Discord, WhatsApp
// ---------------------------------------------------------------------------

const CHANNELS: ChannelDef[] = [
  {
    id: "telegram",
    label: "Telegram",
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
    id: "whatsapp",
    label: "WhatsApp",
    fields: [], // WhatsApp uses QR pairing via web.login.start
  },
  {
    id: "discord",
    label: "Discord",
    fields: [
      {
        key: "token",
        label: "Bot Token",
        placeholder: "your-discord-bot-token",
        sensitive: true,
        help: "From Discord Developer Portal \u2192 Bot \u2192 Token",
      },
      {
        key: "userId",
        label: "Your Discord User ID",
        placeholder: "123456789012345678",
        sensitive: false,
        help: "Enable Developer Mode in Discord settings, then right-click your name to copy ID",
      },
    ],
  },
];

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function ChannelSetupStep({ onComplete }: { onComplete: () => void }) {
  const [expandedChannel, setExpandedChannel] = useState<string | null>(null);
  const [connectedChannels, setConnectedChannels] = useState<Set<string>>(new Set());
  const [fieldValues, setFieldValues] = useState<Record<string, Record<string, string>>>({});
  const [showSecrets, setShowSecrets] = useState<Record<string, boolean>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState<string | null>(null);

  // WhatsApp state
  const [qrDataUrl, setQrDataUrl] = useState<string | null>(null);
  const [waMessage, setWaMessage] = useState<string | null>(null);
  const [waBusy, setWaBusy] = useState<string | null>(null);
  const [waLoginFailed, setWaLoginFailed] = useState(false);

  const { data: configData } = useGatewayRpc<ConfigSnapshot>("config.get");
  const callRpc = useGatewayRpcMutation();

  const hasConnected = connectedChannels.size > 0;

  // ---- Toggle accordion ----
  const toggleChannel = (id: string) => {
    setExpandedChannel((prev) => (prev === id ? null : id));
  };

  // ---- Field value helpers ----
  const getFieldValue = useCallback((channelId: string, fieldKey: string): string => {
    return fieldValues[channelId]?.[fieldKey] ?? "";
  }, [fieldValues]);

  const setFieldValue = (channelId: string, fieldKey: string, value: string) => {
    setFieldValues((prev) => ({
      ...prev,
      [channelId]: { ...prev[channelId], [fieldKey]: value },
    }));
    // Clear error on edit
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

      // Validate all fields are filled
      for (const field of channel.fields) {
        if (field.key === "userId") continue; // optional
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
        // Build channel config patch
        const channelPatch: Record<string, unknown> = {};
        const userId = getFieldValue(channel.id, "userId");
        for (const field of channel.fields) {
          if (field.key === "userId") continue; // userId goes into allowFrom, not channel config
          channelPatch[field.key] = getFieldValue(channel.id, field.key);
        }
        if (userId.trim()) {
          channelPatch.allowFrom = [userId.trim()];
        }

        await callRpc("config.patch", {
          raw: JSON.stringify({ channels: { [channel.id]: channelPatch } }),
          baseHash: snapshot.hash,
        });

        // Wait for gateway restart, then probe
        await new Promise((r) => setTimeout(r, 3000));
        const status = await callRpc<{
          channelAccounts: Record<string, { connected?: boolean; configured?: boolean; running?: boolean }[]>;
        }>("channels.status", { probe: true, timeoutMs: 8000 });

        const accounts = status?.channelAccounts?.[channel.id];
        const account = accounts?.[0];
        const isConnected = account?.configured === true || account?.running === true;

        if (isConnected) {
          setConnectedChannels((prev) => new Set([...prev, channel.id]));
          setExpandedChannel(null); // auto-collapse
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
      // The WhatsApp plugin only registers web.login.start/wait when enabled: true
      // in openclaw.json. Enable it via config.patch if not already on, then wait
      // for the gateway to restart and load the plugin before calling web.login.start.
      const snapshot = configData as ConfigSnapshot | undefined;
      const waAlreadyEnabled =
        (snapshot?.config as Record<string, unknown> | undefined)?.channels !== undefined &&
        ((snapshot?.config as Record<string, Record<string, unknown>>)
          ?.channels?.["whatsapp"] as { enabled?: boolean } | undefined)?.enabled === true;

      if (!waAlreadyEnabled && snapshot?.hash) {
        setWaMessage("Enabling WhatsApp…");
        await callRpc("config.patch", {
          raw: JSON.stringify({ channels: { whatsapp: { enabled: true, dmPolicy: "pairing" } } }),
          baseHash: snapshot.hash,
        });
        // Wait for gateway to restart and load the WhatsApp plugin
        await new Promise((r) => setTimeout(r, 4000));
        setWaMessage(null);
      }

      // Use force: true if a previous login failed (stale creds on disk)
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
      setWaMessage(null);
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
        setExpandedChannel(null); // auto-collapse
      } else {
        // Check if this is a 515 "restart required" failure — the QR pairing
        // may have actually succeeded but the in-process socket restart failed
        // (race between async credential save and socket reconnect on EFS).
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
        // 515 = WhatsApp asked for a restart after pairing. The creds were
        // likely saved; don't delete them. Instead try to verify + recover.
        const recovered = await attemptWhatsApp515Recovery();
        if (recovered) return;
      }

      // Non-515 failure — wipe bad creds so the health monitor doesn't crash-loop
      setWaLoginFailed(true);
      setQrDataUrl(null);
      setWaMessage(null);
      if (!is515) {
        try {
          await callRpc("channels.logout", { channel: "whatsapp" });
        } catch {
          // Logout cleanup is best-effort
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

  /**
   * After a 515 error, the QR pairing likely succeeded but the in-process
   * socket restart failed. Wait for creds to flush to EFS, then check
   * channels.status. If linked, trigger a config reload to start the channel.
   */
  const attemptWhatsApp515Recovery = async (): Promise<boolean> => {
    setWaMessage("Verifying WhatsApp pairing...");
    try {
      // Wait for credential save to complete on EFS
      await new Promise((r) => setTimeout(r, 3000));

      // Check if WhatsApp is actually linked (creds exist on disk)
      const status = await callRpc<{
        channelAccounts: Record<string, { linked?: boolean; configured?: boolean }[]>;
      }>("channels.status", {});
      const waAccounts = status?.channelAccounts?.whatsapp;
      const linked = waAccounts?.some((a) => a.linked || a.configured);

      if (!linked) {
        return false; // Creds didn't save — real failure
      }

      // Pairing succeeded! Trigger a config reload to start the channel.
      // config.patch with the existing WhatsApp config is a no-op write
      // that triggers a gateway restart, which clears manuallyStopped and
      // starts the WhatsApp channel with the saved creds.
      const snapshot = configData as ConfigSnapshot | undefined;
      if (snapshot?.hash) {
        await callRpc("config.patch", {
          raw: JSON.stringify({ channels: { whatsapp: { dmPolicy: "pairing" } } }),
          baseHash: snapshot.hash,
        });
        // Wait for gateway restart to complete
        await new Promise((r) => setTimeout(r, 4000));
      }

      // Success — mark WhatsApp as connected
      setQrDataUrl(null);
      setWaMessage(null);
      setWaLoginFailed(false);
      setConnectedChannels((prev) => new Set([...prev, "whatsapp"]));
      setExpandedChannel(null);
      return true;
    } catch {
      return false; // Recovery failed — let caller handle
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
  return (
    <div className="space-y-4">
      <div className="text-center space-y-1">
        <h2 className="text-lg font-semibold">Connect your channels</h2>
        <p className="text-sm text-muted-foreground">
          Optionally connect messaging platforms to your agent.
        </p>
      </div>

      {/* Accordion list */}
      <div className="space-y-2">
        {CHANNELS.map((channel) => {
          const isExpanded = expandedChannel === channel.id;
          const isConnected = connectedChannels.has(channel.id);
          const isSaving = saving === channel.id;
          const error = errors[channel.id];
          const isWhatsApp = channel.id === "whatsapp";

          return (
            <div
              key={channel.id}
              className="rounded-lg border border-border overflow-hidden"
            >
              {/* Accordion header */}
              <button
                type="button"
                onClick={() => !isConnected && toggleChannel(channel.id)}
                disabled={isConnected}
                className="w-full flex items-center justify-between p-4 text-left hover:bg-muted/30 transition-colors disabled:cursor-default"
              >
                <span className="text-sm font-medium">{channel.label}</span>
                <div className="flex items-center gap-2">
                  {isConnected ? (
                    <span className="inline-flex items-center gap-1.5 text-xs text-green-600 font-medium">
                      <CheckCircle className="h-3.5 w-3.5" />
                      Connected
                    </span>
                  ) : isExpanded ? (
                    <ChevronDown className="h-4 w-4 text-muted-foreground" />
                  ) : (
                    <ChevronRight className="h-4 w-4 text-muted-foreground" />
                  )}
                </div>
              </button>

              {/* Accordion body */}
              {isExpanded && !isConnected && (
                <div className="px-4 pb-4 space-y-3">
                  {/* Credential fields (Telegram/Discord) */}
                  {channel.fields.map((field) => (
                    <div key={field.key} className="space-y-1">
                      <label className="text-xs font-medium">{field.label}</label>
                      <div className="relative">
                        <input
                          type={field.sensitive && !showSecrets[`${channel.id}.${field.key}`] ? "password" : "text"}
                          value={getFieldValue(channel.id, field.key)}
                          placeholder={field.placeholder}
                          onChange={(e) => setFieldValue(channel.id, field.key, e.target.value)}
                          disabled={isSaving}
                          className="w-full rounded-md border border-border bg-background px-3 py-1.5 text-xs font-mono placeholder:text-muted-foreground/40 focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-50"
                        />
                        {field.sensitive && (
                          <button
                            type="button"
                            onClick={() =>
                              setShowSecrets((prev) => ({
                                ...prev,
                                [`${channel.id}.${field.key}`]: !prev[`${channel.id}.${field.key}`],
                              }))
                            }
                            className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                          >
                            {showSecrets[`${channel.id}.${field.key}`] ? (
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

                  {/* WhatsApp QR flow */}
                  {isWhatsApp && (
                    <div className="space-y-3">
                      <p className="text-xs text-muted-foreground">
                        Scan a QR code with WhatsApp on your phone to pair.
                      </p>

                      {/* Error recovery banner */}
                      {waLoginFailed && (
                        <div className="flex items-start gap-2 rounded-md border border-yellow-500/30 bg-yellow-500/10 p-2.5">
                          <AlertTriangle className="h-3.5 w-3.5 text-yellow-500 mt-0.5 shrink-0" />
                          <div className="text-xs text-yellow-200 space-y-1">
                            <p>Previous login failed. Session has been cleared.</p>
                            <p className="text-yellow-200/60">Click &ldquo;Show QR Code&rdquo; to get a fresh code and try again.</p>
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
                          <Image
                            src={qrDataUrl}
                            alt="WhatsApp QR Code"
                            width={192}
                            height={192}
                            unoptimized
                            className="rounded border border-border"
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
                  {error && (
                    <p className="text-xs text-red-500">{error}</p>
                  )}

                  {/* Connect button (Telegram/Discord only) */}
                  {!isWhatsApp && (
                    <Button
                      size="sm"
                      onClick={() => handleConnect(channel)}
                      disabled={isSaving}
                    >
                      {isSaving ? (
                        <Loader2 className="h-3 w-3 animate-spin mr-1" />
                      ) : null}
                      Connect
                    </Button>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Skip / Continue */}
      <div className="flex items-center justify-between pt-2">
        <button
          type="button"
          onClick={onComplete}
          className="text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          Skip
        </button>
        <Button onClick={onComplete} disabled={!hasConnected}>
          Continue
        </Button>
      </div>
    </div>
  );
}
