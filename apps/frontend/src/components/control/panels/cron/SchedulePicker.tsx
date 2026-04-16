"use client";

import { useMemo } from "react";
import cronstrue from "cronstrue";
import { CronExpressionParser } from "cron-parser";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { formatAbsoluteTime } from "./formatters";
import type { CronScheduleKind } from "./types";

/**
 * Raw schedule fields as stored in FormState. SchedulePicker is a controlled
 * component: the parent owns the fields and receives per-field updates via
 * onFieldChange. This matches the existing JobEditDialog `update` pattern.
 */
export interface SchedulePickerFields {
  scheduleKind: CronScheduleKind;
  cronExpr: string;
  cronTz: string;
  everyValue: number;
  everyUnit: "minutes" | "hours" | "days";
  atDatetime: string;
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

export function SchedulePicker({
  scheduleKind,
  cronExpr,
  cronTz,
  everyValue,
  everyUnit,
  atDatetime,
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

  const nextFires = useMemo(() => {
    if (scheduleKind !== "cron") return { fires: [], error: null };
    const expr = cronExpr.trim();
    if (!expr) return { fires: [], error: null };
    return computeNextFires(expr, cronTz, 3);
  }, [scheduleKind, cronExpr, cronTz]);

  return (
    <div className="space-y-2">
      <label className="text-xs font-medium text-[#8a8578]">Schedule</label>
      <div className="flex gap-1">
        {(["cron", "every", "at"] as const).map((kind) => (
          <Button
            key={kind}
            variant={scheduleKind === kind ? "default" : "outline"}
            size="sm"
            onClick={() => onFieldChange("scheduleKind", kind)}
            className="text-xs"
          >
            {kind === "cron"
              ? "Cron Expression"
              : kind === "every"
                ? "Interval"
                : "One-time"}
          </Button>
        ))}
      </div>

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
          {cronExpr.trim() && cronValidation.ok && (
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
                    {cronTz.trim() ? ` (${cronTz.trim()})` : ""}:
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
    </div>
  );
}
