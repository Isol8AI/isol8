// apps/frontend/src/components/control/panels/cron/formatters.ts
import cronstrue from "cronstrue";
import type { CronDelivery, CronSchedule, CronUsageSummary } from "./types";

const CHANNEL_LABELS: Record<string, string> = {
  telegram: "Telegram",
  discord: "Discord",
  slack: "Slack",
  whatsapp: "WhatsApp",
  signal: "Signal",
};

export function formatSchedule(schedule: CronSchedule | undefined): string {
  if (!schedule) return "—";
  switch (schedule.kind) {
    case "at":
      return new Date(schedule.at).toLocaleString();
    case "every": {
      const ms = schedule.everyMs;
      const units: [number, string][] = [
        [24 * 60 * 60 * 1000, "day"],
        [60 * 60 * 1000, "hour"],
        [60 * 1000, "minute"],
        [1000, "second"],
      ];
      for (const [unitMs, label] of units) {
        if (ms % unitMs === 0 && ms >= unitMs) {
          const n = ms / unitMs;
          return `every ${n} ${label}${n === 1 ? "" : "s"}`;
        }
      }
      return `every ${ms}ms`;
    }
    case "cron": {
      try {
        const text = cronstrue.toString(schedule.expr, {
          throwExceptionOnParseError: true,
        });
        return schedule.tz ? `${text} (${schedule.tz})` : text;
      } catch {
        return schedule.expr;
      }
    }
  }
}

export function formatDelivery(delivery: CronDelivery | undefined): string {
  if (!delivery || delivery.mode === "none") return "None";
  if (delivery.mode === "webhook") {
    try {
      const u = new URL(delivery.to ?? "");
      return `Webhook: ${u.host}`;
    } catch {
      return "Webhook";
    }
  }
  // announce
  if (!delivery.channel) return "Chat";
  const label = CHANNEL_LABELS[delivery.channel] ?? delivery.channel;
  return delivery.to ? `${label} ${delivery.to}` : label;
}

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const secs = Math.floor(ms / 1000);
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function formatTokens(usage: CronUsageSummary | undefined): string {
  if (!usage) return "—";
  const parts: string[] = [];
  if (usage.input_tokens) parts.push(`${usage.input_tokens.toLocaleString()} in`);
  if (usage.output_tokens) parts.push(`${usage.output_tokens.toLocaleString()} out`);
  if (usage.cache_read_tokens)
    parts.push(`${usage.cache_read_tokens.toLocaleString()} cache-hit`);
  if (usage.cache_write_tokens)
    parts.push(`${usage.cache_write_tokens.toLocaleString()} cache-write`);
  return parts.join(" · ") || "—";
}

export function formatRelativeTime(
  targetMs: number,
  nowMs: number = Date.now(),
): string {
  const diff = targetMs - nowMs;
  const abs = Math.abs(diff);
  const units: [number, string][] = [
    [24 * 60 * 60 * 1000, "d"],
    [60 * 60 * 1000, "h"],
    [60 * 1000, "m"],
    [1000, "s"],
  ];
  for (const [unit, label] of units) {
    if (abs >= unit) {
      const n = Math.floor(abs / unit);
      return diff < 0 ? `${n}${label} ago` : `in ${n}${label}`;
    }
  }
  return "just now";
}

export function formatAbsoluteTime(ms: number): string {
  return new Date(ms).toLocaleString();
}
