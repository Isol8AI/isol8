import { describe, it, expect } from "vitest";
import {
  buildEditPayloadDiff,
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
