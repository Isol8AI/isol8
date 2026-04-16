import { describe, it, expect } from "vitest";
import {
  formatSchedule,
  formatDelivery,
  formatDuration,
  formatTokens,
  formatRelativeTime,
} from "@/components/control/panels/cron/formatters";
import type { CronDelivery } from "@/components/control/panels/cron/types";

describe("formatSchedule", () => {
  it("formats cron expression with tz", () => {
    expect(
      formatSchedule({ kind: "cron", expr: "0 9 * * *", tz: "America/New_York" }),
    ).toMatch(/9:00 AM|every day at 9/i);
  });
  it("formats every with unit rollup", () => {
    expect(formatSchedule({ kind: "every", everyMs: 60_000 })).toBe("every 1 minute");
    expect(formatSchedule({ kind: "every", everyMs: 60 * 60 * 1000 })).toBe("every 1 hour");
    expect(formatSchedule({ kind: "every", everyMs: 24 * 60 * 60 * 1000 })).toBe("every 1 day");
  });
  it("formats one-shot 'at'", () => {
    expect(formatSchedule({ kind: "at", at: "2026-04-15T09:00:00Z" })).toMatch(/2026/);
  });

  // --- Daily/Weekly preset rendering ---
  it("formats daily 9am as 'Daily at 9:00 AM'", () => {
    expect(formatSchedule({ kind: "cron", expr: "0 9 * * *" })).toBe(
      "Daily at 9:00 AM",
    );
  });
  it("formats weekdays 5pm range as 'Weekdays at 5:00 PM'", () => {
    expect(formatSchedule({ kind: "cron", expr: "0 17 * * 1-5" })).toBe(
      "Weekdays at 5:00 PM",
    );
  });
  it("formats weekdays 5pm list as 'Weekdays at 5:00 PM'", () => {
    expect(formatSchedule({ kind: "cron", expr: "0 17 * * 1,2,3,4,5" })).toBe(
      "Weekdays at 5:00 PM",
    );
  });
  it("formats weekends 8am as 'Weekends at 8:00 AM'", () => {
    expect(formatSchedule({ kind: "cron", expr: "0 8 * * 0,6" })).toBe(
      "Weekends at 8:00 AM",
    );
  });
  it("formats arbitrary day subset as 'Mon, Wed, Fri at ...'", () => {
    expect(formatSchedule({ kind: "cron", expr: "30 14 * * 1,3,5" })).toBe(
      "Mon, Wed, Fri at 2:30 PM",
    );
  });
  it("appends tz when present on a daily-pattern cron", () => {
    expect(
      formatSchedule({ kind: "cron", expr: "0 9 * * *", tz: "America/New_York" }),
    ).toBe("Daily at 9:00 AM (America/New_York)");
  });
  it("falls back to cronstrue for non-daily cron expressions", () => {
    // A stepped expression isn't a Daily/Weekly preset — must NOT be matched.
    const out = formatSchedule({ kind: "cron", expr: "*/15 * * * *" });
    expect(out).not.toMatch(/Daily|Weekdays|Weekends/);
    expect(out.toLowerCase()).toContain("15 minutes");
  });
});

describe("formatDelivery", () => {
  it("returns 'None' when mode=none or delivery is undefined", () => {
    expect(formatDelivery(undefined)).toBe("None");
    expect(formatDelivery({ mode: "none" })).toBe("None");
  });
  it("returns channel + target for announce with channel", () => {
    const d: CronDelivery = { mode: "announce", channel: "telegram", to: "@me" };
    expect(formatDelivery(d)).toBe("Telegram @me");
  });
  it("returns 'Chat' for announce without channel", () => {
    expect(formatDelivery({ mode: "announce" })).toBe("Chat");
  });
  it("returns 'Webhook: …' for webhook mode", () => {
    expect(
      formatDelivery({ mode: "webhook", to: "https://example.com/hook" }),
    ).toMatch(/Webhook.*example\.com/);
  });
});

describe("formatDuration", () => {
  it("ms < 1s shows ms", () => {
    expect(formatDuration(450)).toBe("450ms");
  });
  it("1s–60s shows seconds with 1 decimal", () => {
    expect(formatDuration(14_200)).toBe("14.2s");
  });
  it(">= 60s shows m:ss", () => {
    expect(formatDuration(125_000)).toBe("2:05");
  });
});

describe("formatTokens", () => {
  it("hides zeros", () => {
    expect(
      formatTokens({ input_tokens: 2341, output_tokens: 847, cache_read_tokens: 0 }),
    ).toBe("2,341 in · 847 out");
  });
  it("shows cache hits when present", () => {
    expect(
      formatTokens({ input_tokens: 100, output_tokens: 50, cache_read_tokens: 1120 }),
    ).toBe("100 in · 50 out · 1,120 cache-hit");
  });
});

describe("formatRelativeTime", () => {
  it("returns '2m ago' for 2 minutes past", () => {
    const now = Date.now();
    expect(formatRelativeTime(now - 120_000, now)).toBe("2m ago");
  });
  it("returns 'in 4h' for future", () => {
    const now = Date.now();
    expect(formatRelativeTime(now + 4 * 60 * 60 * 1000, now)).toBe("in 4h");
  });
});
