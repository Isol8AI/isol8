export interface ChannelAccountSnapshot {
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

export interface ChannelsStatusSnapshot {
  ts: number;
  channelOrder: string[];
  channelLabels: Record<string, string>;
  channelDetailLabels?: Record<string, string>;
  channels: Record<string, unknown>;
  channelAccounts: Record<string, ChannelAccountSnapshot[]>;
  channelDefaultAccountId: Record<string, string>;
}

export interface ConfigSnapshot {
  path: string;
  exists: boolean;
  raw: string | null;
  config: Record<string, unknown>;
  hash?: string;
  valid: boolean;
  issues?: { path: string; message: string }[];
}

export interface WebLoginResult {
  message?: string;
  qrDataUrl?: string;
  connected?: boolean;
}

export interface ChannelField {
  key: string;
  label: string;
  placeholder: string;
  sensitive: boolean;
  help?: string;
}

export const CHANNEL_CONFIG_FIELDS: Record<string, ChannelField[]> = {
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

export const DEFAULT_STATUS_FIELDS = [
  "configured",
  "linked",
  "running",
  "connected",
] as const;

export const EXTENDED_STATUS_FIELDS = [
  ...DEFAULT_STATUS_FIELDS,
  "mode",
  "lastConnectedAt",
  "lastInboundAt",
  "lastOutboundAt",
  "lastError",
] as const;

export const STATUS_LABELS: Record<string, string> = {
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

export const REDACTED_SENTINEL = "__OPENCLAW_REDACTED__";

export function formatTimestamp(ts: number | null | undefined): string {
  if (!ts) return "n/a";
  const now = Date.now();
  const diffMs = now - ts;
  if (diffMs < 60_000) return "just now";
  if (diffMs < 3_600_000) return `${Math.floor(diffMs / 60_000)}m ago`;
  if (diffMs < 86_400_000) return `${Math.floor(diffMs / 3_600_000)}h ago`;
  return new Date(ts).toLocaleDateString();
}

export function formatValue(
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

export function isWhatsAppChannel(channelId: string): boolean {
  return channelId === "whatsapp" || channelId === "web";
}

export function getChannelConfig(
  config: Record<string, unknown>,
  channelId: string,
): Record<string, unknown> {
  const channels = config?.channels as Record<string, unknown> | undefined;
  if (!channels) return {};
  const channelConfig = channels[channelId];
  if (typeof channelConfig === "object" && channelConfig !== null) {
    return channelConfig as Record<string, unknown>;
  }
  return {};
}
