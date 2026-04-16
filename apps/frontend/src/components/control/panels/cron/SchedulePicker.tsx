"use client";

import { useMemo } from "react";
import cronstrue from "cronstrue";
import { CronExpressionParser } from "cron-parser";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { buildDailyCronExpr } from "./dailyPattern";
import { formatAbsoluteTime } from "./formatters";
import type { ScheduleKind } from "./formState";

/**
 * Raw schedule fields as stored in FormState. SchedulePicker is a controlled
 * component: the parent owns the fields and receives per-field updates via
 * onFieldChange. This matches the existing JobEditDialog `update` pattern.
 */
export interface SchedulePickerFields {
  scheduleKind: ScheduleKind;
  cronExpr: string;
  cronTz: string;
  everyValue: number;
  everyUnit: "minutes" | "hours" | "days";
  atDatetime: string;
  dailyTime: string;
  dailyDaysOfWeek: number[];
}

export type SchedulePickerField = keyof SchedulePickerFields;

export interface SchedulePickerProps extends SchedulePickerFields {
  onFieldChange: <K extends SchedulePickerField>(
    key: K,
    value: SchedulePickerFields[K],
  ) => void;
}

/**
 * scheduleIsValid — pure helper so JobEditDialog can gate `canSubmit` without
 * observing internal component state. Mirrors the old validation in
 * JobEditDialog.canSubmit.
 */
export function scheduleIsValid(fields: SchedulePickerFields): boolean {
  switch (fields.scheduleKind) {
    case "cron": {
      const expr = fields.cronExpr.trim();
      if (!expr) return false;
      try {
        cronstrue.toString(expr, { throwExceptionOnParseError: true });
      } catch {
        return false;
      }
      if (fields.cronTz.trim()) {
        try {
          CronExpressionParser.parse(expr, { tz: fields.cronTz.trim() });
        } catch {
          return false;
        }
      }
      return true;
    }
    case "daily":
      return (
        fields.dailyDaysOfWeek.length > 0 &&
        /^\d{1,2}:\d{2}$/.test(fields.dailyTime)
      );
    case "every":
      return fields.everyValue > 0;
    case "at":
      return !!fields.atDatetime;
  }
}

function computeNextFires(
  expr: string,
  tz: string,
  count = 3,
): { fires: Date[]; error: string | null } {
  try {
    const iter = CronExpressionParser.parse(expr, {
      tz: tz.trim() || undefined,
    });
    const fires: Date[] = [];
    for (let i = 0; i < count; i++) {
      fires.push(iter.next().toDate());
    }
    return { fires, error: null };
  } catch (e) {
    return {
      fires: [],
      error: e instanceof Error ? e.message : "Parse error",
    };
  }
}

// Sunday-first single-letter labels for the Daily/Weekly day toggles. Matches
// JS `Date.prototype.getDay()` ordering so `daysOfWeek[getDay(d)]` lights up
// the correct button.
const DAY_LETTERS = ["S", "M", "T", "W", "T", "F", "S"];
const DAY_ARIA = [
  "Sunday",
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
];

// Tab order: friendly presets first, escape hatch last.
const KIND_ORDER: ScheduleKind[] = ["daily", "every", "at", "cron"];
const KIND_LABELS: Record<ScheduleKind, string> = {
  daily: "Daily/Weekly",
  every: "Interval",
  at: "One-time",
  cron: "Advanced",
};

export function SchedulePicker({
  scheduleKind,
  cronExpr,
  cronTz,
  everyValue,
  everyUnit,
  atDatetime,
  dailyTime,
  dailyDaysOfWeek,
  onFieldChange,
}: SchedulePickerProps) {
  const cronValidation = useMemo<{
    ok: boolean;
    description?: string;
    error?: string;
  }>(() => {
    const expr = cronExpr.trim();
    if (!expr) return { ok: false };
    try {
      const description = cronstrue.toString(expr, {
        throwExceptionOnParseError: true,
      });
      return { ok: true, description };
    } catch (e) {
      return {
        ok: false,
        error: e instanceof Error ? e.message : "Parse error",
      };
    }
  }, [cronExpr]);

  // Effective cron expression used for the shared next-fires preview. For
  // daily we synthesise the expression from the friendly fields so the user
  // sees the same live preview as the Advanced tab without ever having to
  // read the cron syntax themselves.
  const effectiveExpr = useMemo(() => {
    if (scheduleKind === "cron") return cronExpr.trim();
    if (scheduleKind === "daily" && dailyDaysOfWeek.length > 0) {
      return buildDailyCronExpr(dailyTime, dailyDaysOfWeek);
    }
    return "";
  }, [scheduleKind, cronExpr, dailyTime, dailyDaysOfWeek]);

  // Daily mode has no tz picker, so pass "" (= local) to computeNextFires.
  // Cron mode still honours the form's tz input.
  const effectiveTz = scheduleKind === "cron" ? cronTz : "";

  const nextFires = useMemo(() => {
    if (scheduleKind !== "cron" && scheduleKind !== "daily") {
      return { fires: [], error: null };
    }
    if (!effectiveExpr) return { fires: [], error: null };
    return computeNextFires(effectiveExpr, effectiveTz, 3);
  }, [scheduleKind, effectiveExpr, effectiveTz]);

  // Only render the preview block when we have a valid expression to
  // preview. For cron that means cronstrue parses; for daily the UI guards
  // against empty days so `effectiveExpr` being set implies validity.
  const showPreview =
    (scheduleKind === "cron" && cronExpr.trim() !== "" && cronValidation.ok) ||
    (scheduleKind === "daily" && effectiveExpr !== "");

  const toggleDay = (day: number) => {
    const next = dailyDaysOfWeek.includes(day)
      ? dailyDaysOfWeek.filter((d) => d !== day)
      : [...dailyDaysOfWeek, day].sort((a, b) => a - b);
    onFieldChange("dailyDaysOfWeek", next);
  };

  return (
    <div className="space-y-2">
      <label className="text-xs font-medium text-[#8a8578]">Schedule</label>
      <div className="flex gap-1 flex-wrap">
        {KIND_ORDER.map((kind) => (
          <Button
            key={kind}
            variant={scheduleKind === kind ? "default" : "outline"}
            size="sm"
            onClick={() => onFieldChange("scheduleKind", kind)}
            className="text-xs"
          >
            {KIND_LABELS[kind]}
          </Button>
        ))}
      </div>

      {scheduleKind === "daily" && (
        <div className="space-y-2">
          {/* Quick-select chips */}
          <div className="flex gap-1 flex-wrap">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="text-xs h-7"
              onClick={() =>
                onFieldChange("dailyDaysOfWeek", [0, 1, 2, 3, 4, 5, 6])
              }
            >
              Every day
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="text-xs h-7"
              onClick={() => onFieldChange("dailyDaysOfWeek", [1, 2, 3, 4, 5])}
            >
              Weekdays
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="text-xs h-7"
              onClick={() => onFieldChange("dailyDaysOfWeek", [0, 6])}
            >
              Weekends
            </Button>
          </div>

          {/* Day toggles */}
          <div
            className="flex gap-1"
            role="group"
            aria-label="Days of week"
            data-testid="schedule-picker-daily-days"
          >
            {DAY_LETTERS.map((letter, i) => {
              const selected = dailyDaysOfWeek.includes(i);
              return (
                <Button
                  key={i}
                  type="button"
                  variant={selected ? "default" : "outline"}
                  size="sm"
                  aria-label={DAY_ARIA[i]}
                  aria-pressed={selected}
                  onClick={() => toggleDay(i)}
                  className="text-xs w-8 px-0"
                >
                  {letter}
                </Button>
              );
            })}
          </div>

          {/* Time */}
          <div className="flex items-center gap-2">
            <span className="text-sm text-[#8a8578]">At</span>
            <Input
              type="time"
              value={dailyTime}
              onChange={(e) => onFieldChange("dailyTime", e.target.value)}
              aria-label="Time of day"
              className="h-8 text-sm w-32"
            />
          </div>
        </div>
      )}

      {scheduleKind === "cron" && (
        <div className="space-y-1.5">
          <div className="flex gap-2">
            <Input
              value={cronExpr}
              onChange={(e) => onFieldChange("cronExpr", e.target.value)}
              placeholder="0 9 * * *"
              aria-label="Cron expression"
              className={cn(
                "h-8 text-sm font-mono flex-1",
                cronExpr.trim() &&
                  !cronValidation.ok &&
                  "border-destructive focus-visible:ring-destructive",
              )}
            />
            <Input
              value={cronTz}
              onChange={(e) => onFieldChange("cronTz", e.target.value)}
              placeholder="Timezone (optional)"
              aria-label="Timezone"
              className="h-8 text-sm w-40"
            />
          </div>
          {cronExpr.trim() &&
            (cronValidation.ok ? (
              <p className="text-xs text-[#2d8a4e]">
                {cronValidation.description}
              </p>
            ) : (
              <p className="text-xs text-destructive">
                {cronValidation.error ?? "Parse error"}
              </p>
            ))}
        </div>
      )}

      {scheduleKind === "every" && (
        <div className="flex gap-2 items-center">
          <span className="text-sm text-[#8a8578]">Every</span>
          <Input
            type="number"
            min={1}
            value={everyValue}
            onChange={(e) =>
              onFieldChange(
                "everyValue",
                Math.max(1, parseInt(e.target.value) || 1),
              )
            }
            aria-label="Interval value"
            className="h-8 text-sm w-20"
          />
          <select
            value={everyUnit}
            onChange={(e) =>
              onFieldChange(
                "everyUnit",
                e.target.value as "minutes" | "hours" | "days",
              )
            }
            aria-label="Interval unit"
            className="h-8 rounded-md border border-[#e0dbd0] bg-[#faf7f2] px-2 text-sm"
          >
            <option value="minutes">minutes</option>
            <option value="hours">hours</option>
            <option value="days">days</option>
          </select>
        </div>
      )}

      {scheduleKind === "at" && (
        <Input
          type="datetime-local"
          value={atDatetime}
          onChange={(e) => onFieldChange("atDatetime", e.target.value)}
          aria-label="Run at"
          className="h-8 text-sm"
        />
      )}

      {/* Shared next-fires preview. Used by cron (Advanced) and daily — both
          serialise to a cron expression that we feed through cron-parser. */}
      {showPreview && (
        <div
          className="mt-1 space-y-0.5"
          data-testid="schedule-picker-next-fires"
        >
          {nextFires.error ? (
            <p className="text-xs text-destructive">Parse error</p>
          ) : nextFires.fires.length > 0 ? (
            <>
              <p className="text-xs text-[#8a8578]">
                Next fires
                {effectiveTz.trim() ? ` (${effectiveTz.trim()})` : ""}:
              </p>
              <ul className="text-xs text-[#8a8578] pl-2 space-y-0.5">
                {nextFires.fires.map((d, i) => (
                  <li key={i}>{formatAbsoluteTime(d.getTime())}</li>
                ))}
              </ul>
            </>
          ) : null}
        </div>
      )}
    </div>
  );
}
