import { describe, it, expect } from "vitest";
import {
  buildEditPayloadDiff,
  buildSchedule,
  EMPTY_FORM,
  jobToForm,
  type FormState,
} from "@/components/control/panels/cron/formState";
import type { CronJob } from "@/components/control/panels/cron/types";

const baseJob: CronJob = {
  id: "job-1",
  name: "Daily digest",
  enabled: true,
  createdAtMs: 1_700_000_000_000,
  updatedAtMs: 1_700_000_000_000,
  schedule: { kind: "cron", expr: "0 7 * * *", tz: "UTC" },
  sessionTarget: "isolated",
  wakeMode: "next-heartbeat",
  payload: {
    kind: "agentTurn",
    message: "Summarize news",
    model: "claude-3-5-sonnet",
    fallbacks: ["claude-3-haiku"],
    timeoutSeconds: 120,
    thinking: "high",
    lightContext: true,
    toolsAllow: ["web.search"],
  },
  delivery: { mode: "announce" },
  agentId: "agent-x",
  deleteAfterRun: true,
  state: {},
};

describe("buildEditPayloadDiff", () => {
  it("emits explicit clearing values when the user empties optional overrides", () => {
    // Start from the job's form, then clear every optional override.
    const cleared: FormState = {
      ...jobToForm(baseJob),
      model: undefined,
      fallbacks: undefined,
      timeoutSeconds: undefined,
      thinking: undefined,
      lightContext: false,
      toolsAllow: undefined,
      delivery: undefined,
      agentId: undefined,
      deleteAfterRun: false,
    };

    const patch = buildEditPayloadDiff(cleared, baseJob);

    expect(patch.payload).toMatchObject({
      kind: "agentTurn",
      message: "Summarize news",
      model: null,
      fallbacks: null,
      timeoutSeconds: null,
      thinking: null,
      lightContext: false,
      toolsAllow: null,
    });
    expect(patch.delivery).toEqual({ mode: "none" });
    // Top-level agentId clears with null (cast escape).
    expect((patch as { agentId?: string | null }).agentId).toBeNull();
    expect(patch.deleteAfterRun).toBe(false);
  });

  it("includes new non-empty overrides without clearing markers", () => {
    const form: FormState = {
      ...jobToForm(baseJob),
      model: "claude-3-5-haiku",
      timeoutSeconds: 60,
      lightContext: false, // was true on the job → must include false to clear
    };

    const patch = buildEditPayloadDiff(form, baseJob);

    expect(patch.payload).toMatchObject({
      kind: "agentTurn",
      model: "claude-3-5-haiku",
      timeoutSeconds: 60,
      lightContext: false,
    });
  });

  it("explicitly clears delivery.failureDestination with null when removed", () => {
    // Original job has a nested failureDestination set on its delivery.
    const jobWithFailureDest: CronJob = {
      ...baseJob,
      delivery: {
        mode: "announce",
        channel: "slack",
        to: "#alerts",
        failureDestination: {
          mode: "webhook",
          channel: "webhook",
          to: "https://example.com/hook",
        },
      },
    };
    // Form: user kept the delivery but removed the nested failureDestination.
    const form: FormState = {
      ...jobToForm(jobWithFailureDest),
      delivery: {
        mode: "announce",
        channel: "slack",
        to: "#alerts",
        // failureDestination omitted on purpose — DeliveryPicker sets it
        // to undefined when the user clears the nested picker.
      },
    };

    const patch = buildEditPayloadDiff(form, jobWithFailureDest);

    // Patch must explicitly carry `failureDestination: null` so the backend
    // clears the prior value (JSON.stringify drops undefined keys, so we
    // need null, matching the P1 delivery clearing convention).
    expect(patch.delivery).toBeDefined();
    expect(
      (patch.delivery as { failureDestination?: unknown } | undefined)
        ?.failureDestination,
    ).toBeNull();
  });

  it("preserves systemEvent payload kind on edit (P1c)", () => {
    const systemJob: CronJob = {
      ...baseJob,
      payload: { kind: "systemEvent", text: "System check" },
    };
    const form: FormState = {
      ...jobToForm(systemJob),
      message: "Updated system check",
    };

    const patch = buildEditPayloadDiff(form, systemJob);

    expect(patch.payload).toEqual({
      kind: "systemEvent",
      text: "Updated system check",
    });
  });

  it("omits optional payload fields when neither form nor original had them", () => {
    const noOverridesJob: CronJob = {
      ...baseJob,
      payload: { kind: "agentTurn", message: "Hi" },
      delivery: undefined,
      agentId: undefined,
      deleteAfterRun: undefined,
    };
    const form: FormState = {
      ...EMPTY_FORM,
      name: "Hi job",
      message: "Hi",
      scheduleKind: "cron",
      cronExpr: "0 * * * *",
      delivery: undefined,
    };

    const patch = buildEditPayloadDiff(form, noOverridesJob);

    expect(patch.payload).toEqual({ kind: "agentTurn", message: "Hi" });
    // delivery stays absent because original had none either.
    expect(patch.delivery).toBeUndefined();
    expect((patch as { agentId?: string | null }).agentId).toBeUndefined();
  });
});

describe("jobToForm – lossless interval rounding (P1a)", () => {
  it("converts a 90-minute interval to 90 minutes, not 2 hours", () => {
    const job: CronJob = {
      ...baseJob,
      schedule: { kind: "every", everyMs: 5_400_000 }, // 90 minutes
    };
    const form = jobToForm(job);
    expect(form.everyUnit).toBe("minutes");
    expect(form.everyValue).toBe(90);
  });

  it("converts exact hour intervals to hours", () => {
    const job: CronJob = {
      ...baseJob,
      schedule: { kind: "every", everyMs: 7_200_000 }, // 2 hours
    };
    const form = jobToForm(job);
    expect(form.everyUnit).toBe("hours");
    expect(form.everyValue).toBe(2);
  });

  it("converts exact day intervals to days", () => {
    const job: CronJob = {
      ...baseJob,
      schedule: { kind: "every", everyMs: 172_800_000 }, // 2 days
    };
    const form = jobToForm(job);
    expect(form.everyUnit).toBe("days");
    expect(form.everyValue).toBe(2);
  });

  it("converts 36-hour interval to minutes (not exactly hours or days)", () => {
    const job: CronJob = {
      ...baseJob,
      schedule: { kind: "every", everyMs: 129_600_000 }, // 36 hours = 2160 min
    };
    const form = jobToForm(job);
    // 36 hours is not an exact day count, but is an exact hour count
    // 129_600_000 % 3_600_000 === 0 → 36 hours
    expect(form.everyUnit).toBe("hours");
    expect(form.everyValue).toBe(36);
  });
});

describe("jobToForm – local datetime (P1b)", () => {
  it("produces a datetime-local string matching local wall-clock components", () => {
    const isoStr = "2026-04-15T14:30:00.000Z";
    const job: CronJob = {
      ...baseJob,
      schedule: { kind: "at", at: isoStr },
    };
    const form = jobToForm(job);
    // The expected value should match the local-time interpretation of the
    // ISO string, not the raw UTC. We verify by constructing what the local
    // Date components would produce.
    const d = new Date(isoStr);
    const pad = (n: number) => String(n).padStart(2, "0");
    const expected = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
    expect(form.atDatetime).toBe(expected);
  });
});

describe("buildSchedule – Daily/Weekly preset", () => {
  it("default daily 9am every day → '0 9 * * *'", () => {
    const schedule = buildSchedule({
      ...EMPTY_FORM,
      scheduleKind: "daily",
      dailyTime: "09:00",
      dailyDaysOfWeek: [0, 1, 2, 3, 4, 5, 6],
    });
    expect(schedule).toEqual({ kind: "cron", expr: "0 9 * * *" });
  });

  it("daily weekdays 5pm → '0 17 * * 1,2,3,4,5'", () => {
    const schedule = buildSchedule({
      ...EMPTY_FORM,
      scheduleKind: "daily",
      dailyTime: "17:00",
      dailyDaysOfWeek: [1, 2, 3, 4, 5],
    });
    expect(schedule).toEqual({ kind: "cron", expr: "0 17 * * 1,2,3,4,5" });
  });

  it("daily preserves cronTz when present (round-tripped from cron-with-tz)", () => {
    const schedule = buildSchedule({
      ...EMPTY_FORM,
      scheduleKind: "daily",
      dailyTime: "09:00",
      dailyDaysOfWeek: [0, 1, 2, 3, 4, 5, 6],
      cronTz: "America/New_York",
    });
    expect(schedule).toEqual({
      kind: "cron",
      expr: "0 9 * * *",
      tz: "America/New_York",
    });
  });
});

describe("jobToForm – Daily/Weekly round-trip", () => {
  it("loads '0 9 * * *' as daily, every day at 09:00", () => {
    const job: CronJob = {
      ...baseJob,
      schedule: { kind: "cron", expr: "0 9 * * *" },
    };
    const form = jobToForm(job);
    expect(form.scheduleKind).toBe("daily");
    expect(form.dailyTime).toBe("09:00");
    expect(form.dailyDaysOfWeek).toEqual([0, 1, 2, 3, 4, 5, 6]);
  });

  it("loads '30 17 * * 1-5' as daily weekdays at 17:30", () => {
    const job: CronJob = {
      ...baseJob,
      schedule: { kind: "cron", expr: "30 17 * * 1-5" },
    };
    const form = jobToForm(job);
    expect(form.scheduleKind).toBe("daily");
    expect(form.dailyTime).toBe("17:30");
    expect(form.dailyDaysOfWeek).toEqual([1, 2, 3, 4, 5]);
  });

  it("loads '0 9 * * 0,3,5' as daily on Sun/Wed/Fri", () => {
    const job: CronJob = {
      ...baseJob,
      schedule: { kind: "cron", expr: "0 9 * * 0,3,5" },
    };
    const form = jobToForm(job);
    expect(form.scheduleKind).toBe("daily");
    expect(form.dailyDaysOfWeek).toEqual([0, 3, 5]);
  });

  it("falls through to 'cron' kind for non-matching expressions like '*/15 * * * *'", () => {
    const job: CronJob = {
      ...baseJob,
      schedule: { kind: "cron", expr: "*/15 * * * *" },
    };
    const form = jobToForm(job);
    expect(form.scheduleKind).toBe("cron");
    expect(form.cronExpr).toBe("*/15 * * * *");
  });

  it("falls through to 'cron' kind for named days like '0 9 * * MON'", () => {
    const job: CronJob = {
      ...baseJob,
      schedule: { kind: "cron", expr: "0 9 * * MON" },
    };
    const form = jobToForm(job);
    expect(form.scheduleKind).toBe("cron");
  });

  it("falls through to 'cron' kind for stepped DOW like '0 9 * * */2'", () => {
    const job: CronJob = {
      ...baseJob,
      schedule: { kind: "cron", expr: "0 9 * * */2" },
    };
    const form = jobToForm(job);
    expect(form.scheduleKind).toBe("cron");
  });

  it("preserves the original expr+tz so flipping to Advanced reveals them", () => {
    const job: CronJob = {
      ...baseJob,
      schedule: { kind: "cron", expr: "0 9 * * 1-5", tz: "America/New_York" },
    };
    const form = jobToForm(job);
    expect(form.scheduleKind).toBe("daily");
    expect(form.cronExpr).toBe("0 9 * * 1-5");
    expect(form.cronTz).toBe("America/New_York");
  });
});
