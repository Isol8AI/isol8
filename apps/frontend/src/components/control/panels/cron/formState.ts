// apps/frontend/src/components/control/panels/cron/formState.ts
//
// Shared form-state types and helpers used by JobEditDialog and its
// sibling picker components (SchedulePicker, DeliveryPicker, ...).
//
// Extracted from JobEditDialog.tsx in Task 13 so that multiple siblings
// can reference the same FormState without cyclic imports.

import type {
  CronDelivery,
  CronFailureAlert,
  CronJob,
  CronSchedule,
  CronScheduleKind,
  CronWakeMode,
} from "./types";

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

  // --- Agent execution (Task 14) ---
  /** Override primary model; undefined/empty means "use agent default". */
  model?: string;
  /** Ordered list of fallback model ids. */
  fallbacks?: string[];
  /** Hard timeout for a single run in seconds. */
  timeoutSeconds?: number;
  /** Free-text thinking/reasoning hint passed to the model. */
  thinking?: string;
  /** When true, skip loading recent chat history for the run. */
  lightContext?: boolean;

  // --- Tools (Task 15) ---
  /**
   * Agent this cron is scoped to. Used internally (e.g. to filter
   * `tools.catalog` lookups) AND sent as `agentId` at the top-level of the
   * cron.add/update payload (CronJob.agentId is a top-level field).
   */
  agentId?: string;
  /**
   * Allowlist of tool ids the agent may call during this run. Undefined or
   * empty means "all tools allowed" (server default).
   */
  toolsAllow?: string[];

  // --- Failure alerts (Task 16) ---
  /** Master switch for the failure-alert block. When false, serialize `failureAlert: false`. */
  failureAlertEnabled: boolean;
  /** Trigger after this many consecutive failures. */
  failureAlertAfter: number;
  /** Minimum ms between two alerts. */
  failureAlertCooldownMs: number;
  /**
   * Destination for the failure alert. Modelled as a CronDelivery so we can
   * reuse DeliveryPicker (nested); translated to CronFailureAlert's
   * `{channel, to, accountId, mode}` subset on save.
   */
  failureAlertDelivery?: CronDelivery;

  // --- Advanced (Task 16) ---
  /** One-shot jobs: delete after the first successful run. */
  deleteAfterRun: boolean;
  /**
   * How the scheduler dispatches due runs:
   *  - "next-heartbeat" waits for the next scheduler tick (default),
   *  - "now" fires immediately.
   */
  wakeMode: CronWakeMode;
}

export const EMPTY_FORM: FormState = {
  name: "",
  // Create-form defaults (Task 16): pick "Every 1 day" as the most common
  // fresh-cron configuration. User can flip to cron/at in SchedulePicker.
  scheduleKind: "every",
  cronExpr: "",
  cronTz: "",
  everyValue: 1,
  everyUnit: "days",
  atDatetime: "",
  message: "",
  enabled: true,
  // Default: announce to in-chat. Channel dropdown inside DeliveryPicker
  // defaults to "__chat__" which leaves `channel` undefined.
  delivery: { mode: "announce" },
  // Agent-execution defaults: all undefined/empty so the payload omits them.
  model: undefined,
  fallbacks: undefined,
  timeoutSeconds: undefined,
  thinking: undefined,
  lightContext: false,
  agentId: undefined,
  toolsAllow: undefined,
  // Failure alerts: off by default. When user toggles on, defaults below apply.
  failureAlertEnabled: false,
  failureAlertAfter: 3,
  failureAlertCooldownMs: 3_600_000, // 1 hour
  failureAlertDelivery: undefined,
  // Advanced defaults.
  deleteAfterRun: false,
  wakeMode: "next-heartbeat",
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

// --- Failure-alert <-> CronDelivery translation ---
//
// CronFailureAlert has {channel, to, accountId, mode} plus {after, cooldownMs}.
// The destination subset maps cleanly to CronDelivery so we can reuse
// <DeliveryPicker nested />. `mode` on CronFailureAlert is narrower
// ("announce" | "webhook"); when the user somehow ends up with "none" we drop
// the field entirely so the backend can default it.

export function failureAlertToDelivery(
  a: CronFailureAlert | false | undefined,
): CronDelivery | undefined {
  if (!a) return undefined;
  return {
    mode: a.mode ?? "announce",
    channel: a.channel,
    to: a.to,
    accountId: a.accountId,
  };
}

export function deliveryToFailureAlertDest(
  d: CronDelivery | undefined,
): Pick<CronFailureAlert, "channel" | "to" | "accountId" | "mode"> {
  if (!d) return {};
  const out: Pick<CronFailureAlert, "channel" | "to" | "accountId" | "mode"> = {};
  if (d.mode === "announce" || d.mode === "webhook") out.mode = d.mode;
  if (d.channel !== undefined) out.channel = d.channel;
  if (d.to !== undefined) out.to = d.to;
  if (d.accountId !== undefined) out.accountId = d.accountId;
  return out;
}

export function buildFailureAlertPayload(form: FormState): CronFailureAlert | false {
  if (!form.failureAlertEnabled) return false;
  const dest = deliveryToFailureAlertDest(form.failureAlertDelivery);
  return {
    after: form.failureAlertAfter,
    cooldownMs: form.failureAlertCooldownMs,
    ...dest,
  };
}

export function jobToForm(job: CronJob): FormState {
  const s = job.schedule;
  const msg = job.payload?.kind === "agentTurn" ? (job.payload.message ?? "") : (job.payload?.text ?? "");
  const agentExec =
    job.payload?.kind === "agentTurn"
      ? {
          model: job.payload.model,
          fallbacks: job.payload.fallbacks,
          timeoutSeconds: job.payload.timeoutSeconds,
          thinking: job.payload.thinking,
          lightContext: job.payload.lightContext ?? false,
          toolsAllow: job.payload.toolsAllow,
        }
      : {};
  const fa = job.failureAlert; // CronFailureAlert | false | undefined
  const failureAlertFields = {
    failureAlertEnabled: !!fa,
    failureAlertAfter: (fa && typeof fa === "object" ? fa.after : undefined) ?? 3,
    failureAlertCooldownMs:
      (fa && typeof fa === "object" ? fa.cooldownMs : undefined) ?? 3_600_000,
    failureAlertDelivery: failureAlertToDelivery(fa),
  };
  const base = {
    name: job.name,
    message: msg,
    enabled: job.enabled,
    delivery: job.delivery,
    agentId: job.agentId,
    deleteAfterRun: job.deleteAfterRun ?? false,
    wakeMode: job.wakeMode ?? "next-heartbeat",
    ...agentExec,
    ...failureAlertFields,
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
