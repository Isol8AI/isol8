"use client";

// apps/frontend/src/components/control/panels/cron/FailureAlertsSection.tsx
//
// Body for the "Failure alerts" accordion section inside JobEditDialog.
// Extracted in Task 16 to keep JobEditDialog.tsx under the 400-line budget.

import { useState } from "react";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { DeliveryPicker } from "./DeliveryPicker";
import type { FormState } from "./formState";

// Cooldown-unit picker (minutes/hours). Stored on FormState as milliseconds
// to match CronFailureAlert.cooldownMs.

type CooldownUnit = "minutes" | "hours";
const COOLDOWN_MULTIPLIER: Record<CooldownUnit, number> = {
  minutes: 60_000,
  hours: 3_600_000,
};

function pickCooldownUnit(ms: number): CooldownUnit {
  return ms >= 3_600_000 && ms % 3_600_000 === 0 ? "hours" : "minutes";
}

function cooldownValueInUnit(ms: number, unit: CooldownUnit): number {
  return Math.max(1, Math.round(ms / COOLDOWN_MULTIPLIER[unit]));
}

export function FailureAlertsSection({
  form,
  update,
}: {
  form: FormState;
  update: <K extends keyof FormState>(key: K, value: FormState[K]) => void;
}) {
  const [cooldownUnit, setCooldownUnit] = useState<CooldownUnit>(() =>
    pickCooldownUnit(form.failureAlertCooldownMs),
  );

  return (
    <div className="space-y-3">
      {/* Master toggle */}
      <label className="flex items-center gap-2 cursor-pointer">
        <Checkbox
          checked={form.failureAlertEnabled}
          onCheckedChange={(checked) => update("failureAlertEnabled", checked === true)}
        />
        <span className="text-sm">Alert me when this job fails repeatedly</span>
      </label>

      {form.failureAlertEnabled && (
        <div className="pl-6 space-y-3">
          {/* After N failures */}
          <div className="space-y-1">
            <label className="text-xs font-medium text-[#8a8578]">
              Alert after consecutive failures
            </label>
            <Input
              type="number"
              min={1}
              value={form.failureAlertAfter}
              onChange={(e) => {
                const n = Number(e.target.value);
                update("failureAlertAfter", Number.isFinite(n) && n > 0 ? Math.floor(n) : 1);
              }}
              className="h-8 text-sm w-24"
              aria-label="Failure alert after"
            />
          </div>

          {/* Nested delivery picker for the failure destination */}
          <DeliveryPicker
            value={form.failureAlertDelivery}
            onChange={(d) => update("failureAlertDelivery", d)}
            label="Notify failures to"
            nested
          />

          {/* Cooldown */}
          <div className="space-y-1">
            <label className="text-xs font-medium text-[#8a8578]">
              Minimum time between alerts
            </label>
            <div className="flex gap-2">
              <Input
                type="number"
                min={1}
                value={cooldownValueInUnit(form.failureAlertCooldownMs, cooldownUnit)}
                onChange={(e) => {
                  const n = Number(e.target.value);
                  const v = Number.isFinite(n) && n > 0 ? Math.floor(n) : 1;
                  update("failureAlertCooldownMs", v * COOLDOWN_MULTIPLIER[cooldownUnit]);
                }}
                className="h-8 text-sm w-24"
                aria-label="Failure alert cooldown value"
              />
              <select
                value={cooldownUnit}
                onChange={(e) => {
                  const next = e.target.value as CooldownUnit;
                  // Keep displayed value, reinterpreted in the new unit.
                  const displayed = cooldownValueInUnit(form.failureAlertCooldownMs, cooldownUnit);
                  setCooldownUnit(next);
                  update("failureAlertCooldownMs", displayed * COOLDOWN_MULTIPLIER[next]);
                }}
                aria-label="Failure alert cooldown unit"
                className="h-8 rounded-md border border-[#e0dbd0] bg-[#faf7f2] px-2 text-sm"
              >
                <option value="minutes">minutes</option>
                <option value="hours">hours</option>
              </select>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
