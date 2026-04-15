// apps/frontend/src/components/control/panels/cron/formState.ts
//
// Shared form-state types and helpers used by JobEditDialog and its
// sibling picker components (SchedulePicker, DeliveryPicker, ...).
//
// Extracted from JobEditDialog.tsx in Task 13 so that multiple siblings
// can reference the same FormState without cyclic imports.

import type { CronDelivery, CronJob, CronSchedule, CronScheduleKind } from "./types";

export type ScheduleKind = CronScheduleKind;

export interface FormState {
  name: string;
  scheduleKind: ScheduleKind;
  cronExpr: string;
  cronTz: string;
  everyValue: number;
  everyUnit: "minutes" | "hours" | "days";
  atDatetime: string;
  message: string;
  enabled: boolean;
  /**
   * Delivery destination for job results. When undefined at create-time,
   * EMPTY_FORM seeds a default of `{ mode: "announce" }` (Chat).
   */
  delivery?: CronDelivery;
}

export const EMPTY_FORM: FormState = {
  name: "",
  scheduleKind: "cron",
  cronExpr: "",
  cronTz: "",
  everyValue: 30,
  everyUnit: "minutes",
  atDatetime: "",
  message: "",
  enabled: true,
  // Default: announce to in-chat. Channel dropdown inside DeliveryPicker
  // defaults to "__chat__" which leaves `channel` undefined.
  delivery: { mode: "announce" },
};

export function buildSchedule(form: FormState): CronSchedule {
  switch (form.scheduleKind) {
    case "cron":
      return { kind: "cron", expr: form.cronExpr, ...(form.cronTz ? { tz: form.cronTz } : {}) };
    case "every": {
      const multipliers = { minutes: 60000, hours: 3600000, days: 86400000 };
      return { kind: "every", everyMs: form.everyValue * multipliers[form.everyUnit] };
    }
    case "at":
      return { kind: "at", at: new Date(form.atDatetime).toISOString() };
  }
}

export function jobToForm(job: CronJob): FormState {
  const s = job.schedule;
  const msg = job.payload?.kind === "agentTurn" ? (job.payload.message ?? "") : (job.payload?.text ?? "");
  const base = {
    name: job.name,
    message: msg,
    enabled: job.enabled,
    delivery: job.delivery,
  };
  if (s.kind === "cron") {
    return { ...EMPTY_FORM, ...base, scheduleKind: "cron", cronExpr: s.expr ?? "", cronTz: s.tz ?? "" };
  }
  if (s.kind === "every") {
    const ms = s.everyMs ?? 60000;
    if (ms >= 86400000) return { ...EMPTY_FORM, ...base, scheduleKind: "every", everyValue: Math.round(ms / 86400000), everyUnit: "days" };
    if (ms >= 3600000) return { ...EMPTY_FORM, ...base, scheduleKind: "every", everyValue: Math.round(ms / 3600000), everyUnit: "hours" };
    return { ...EMPTY_FORM, ...base, scheduleKind: "every", everyValue: Math.round(ms / 60000), everyUnit: "minutes" };
  }
  if (s.kind === "at") {
    let atDatetime = "";
    try {
      atDatetime = s.at ? new Date(s.at).toISOString().slice(0, 16) : "";
    } catch { /* ignore */ }
    return { ...EMPTY_FORM, ...base, scheduleKind: "at", atDatetime };
  }
  return { ...EMPTY_FORM, ...base };
}
