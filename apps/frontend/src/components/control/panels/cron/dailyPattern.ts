// apps/frontend/src/components/control/panels/cron/dailyPattern.ts
//
// Helpers for the friendly Daily/Weekly schedule preset. The preset is a
// surface for a narrow subset of cron expressions: a fixed minute + hour with
// wildcards on day-of-month and month, and a day-of-week list. We round-trip
// these expressions through the friendly UI so users never need to learn cron
// syntax for the common "every weekday at 9am" case.
//
// Only the subset documented below is recognised; anything more elaborate
// (steps like `*/2`, named days like `MON`, ranges spanning the wraparound)
// falls through to the Advanced (cron) tab so we never silently lossily
// reformat a power-user's expression.

/** Result of parsing a cron expression as a Daily/Weekly preset. */
export interface DailyCronParsed {
  /** Hour of day, 0-23. */
  hour: number;
  /** Minute of hour, 0-59. */
  minute: number;
  /**
   * Days of week as integers, Sunday = 0 through Saturday = 6, sorted ascending
   * with no duplicates. `7` (alternate Sunday) is normalised to `0`.
   */
  daysOfWeek: number[];
}

const DAILY_RE = /^(\d{1,2}) (\d{1,2}) \* \* ([0-7,\-*]+)$/;

/**
 * Parse the day-of-week field of a cron expression into a sorted, deduped
 * 0-6 array (Sunday-first). Returns null on anything we don't recognise so
 * callers can fall through to the Advanced tab.
 *
 * Accepted forms:
 *  - `*`           → all 7 days
 *  - `1-5`         → range
 *  - `0,3,5`       → list
 *  - `1-3,5`       → mixed list+range
 *
 * Rejected (returns null):
 *  - Steps (`*/2`, `1-5/2`)
 *  - Named days (`MON`, `mon`)
 *  - Reversed ranges (`5-2`)
 *  - Out-of-bounds values (`8`, `-1`)
 */
export function parseDow(field: string): number[] | null {
  const trimmed = field.trim();
  if (trimmed === "*") return [0, 1, 2, 3, 4, 5, 6];
  const out = new Set<number>();
  for (const part of trimmed.split(",")) {
    const seg = part.trim();
    if (!seg) return null;
    if (seg.includes("/")) return null;
    if (seg.includes("-")) {
      const [a, b] = seg.split("-");
      if (a === undefined || b === undefined) return null;
      if (!/^\d+$/.test(a) || !/^\d+$/.test(b)) return null;
      let start = Number(a);
      let end = Number(b);
      if (start > 7 || end > 7 || start < 0 || end < 0) return null;
      if (start === 7) start = 0;
      if (end === 7) end = 0;
      if (start > end) return null;
      for (let i = start; i <= end; i++) out.add(i);
    } else {
      if (!/^\d+$/.test(seg)) return null;
      let n = Number(seg);
      if (n < 0 || n > 7) return null;
      if (n === 7) n = 0;
      out.add(n);
    }
  }
  if (out.size === 0) return null;
  return Array.from(out).sort((x, y) => x - y);
}

/**
 * Parse a cron expression as a Daily/Weekly preset. Returns null when the
 * expression doesn't match the narrow `m h * * dow` shape, or when the
 * day-of-week field uses syntax outside `parseDow`'s accepted forms.
 */
export function parseDailyCronExpr(expr: string): DailyCronParsed | null {
  const m = DAILY_RE.exec(expr.trim());
  if (!m) return null;
  // The regex has 3 capture groups; if any are undefined we bail out so
  // the caller can fall through to the Advanced tab.
  const minStr = m[1];
  const hourStr = m[2];
  const dowStr = m[3];
  if (minStr === undefined || hourStr === undefined || dowStr === undefined) {
    return null;
  }
  const minute = Number(minStr);
  const hour = Number(hourStr);
  if (!Number.isFinite(minute) || !Number.isFinite(hour)) return null;
  if (minute < 0 || minute > 59 || hour < 0 || hour > 23) return null;
  const daysOfWeek = parseDow(dowStr);
  if (!daysOfWeek) return null;
  return { hour, minute, daysOfWeek };
}

/**
 * Build the day-of-week field for a Daily/Weekly preset cron expression. We
 * deliberately avoid range compression (`1,2,3,4,5` instead of `1-5`) to keep
 * the encoder dead simple; the parser accepts both shapes for round-trips.
 */
export function buildDailyDowExpr(daysOfWeek: number[]): string {
  if (daysOfWeek.length === 7) return "*";
  return [...daysOfWeek].sort((a, b) => a - b).join(",");
}

/**
 * Build a `m h * * dow` cron expression for the Daily/Weekly preset. `time`
 * is an `HH:mm` string from a native `<input type="time">`.
 */
export function buildDailyCronExpr(time: string, daysOfWeek: number[]): string {
  const [hh, mm] = parseTimeHHmm(time);
  return `${mm} ${hh} * * ${buildDailyDowExpr(daysOfWeek)}`;
}

/**
 * Parse an `HH:mm` (or `H:mm`) time string into `[hour, minute]`. Falls back
 * to `[9, 0]` on malformed input — daily preset's UI guards against this with
 * a `<input type="time">`, so the fallback is purely defensive.
 */
export function parseTimeHHmm(time: string): [number, number] {
  const m = /^(\d{1,2}):(\d{2})$/.exec(time.trim());
  if (!m) return [9, 0];
  const hh = Math.max(0, Math.min(23, Number(m[1])));
  const mm = Math.max(0, Math.min(59, Number(m[2])));
  return [hh, mm];
}

/**
 * Format a 24-hour `(hour, minute)` pair as a 12-hour string with am/pm. We
 * roll our own instead of `toLocaleTimeString` to keep the format stable
 * across runtimes/locales (tests and snapshots rely on a fixed shape).
 */
export function formatTime12h(hour: number, minute: number): string {
  const period = hour >= 12 ? "PM" : "AM";
  const h12 = hour % 12 === 0 ? 12 : hour % 12;
  const mm = String(minute).padStart(2, "0");
  return `${h12}:${mm} ${period}`;
}
