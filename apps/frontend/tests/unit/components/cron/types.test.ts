// apps/frontend/tests/unit/components/cron/types.test.ts
import { expectTypeOf, describe, it } from "vitest";
import type {
  CronJob,
  CronJobPatch,
  CronDelivery,
  CronAgentTurnPayload,
} from "@/components/control/panels/cron/types";

describe("cron types", () => {
  it("CronJob.payload narrows on kind", () => {
    const job = { payload: { kind: "agentTurn", message: "" } } as CronJob;
    if (job.payload.kind === "agentTurn") {
      expectTypeOf(job.payload).toEqualTypeOf<CronAgentTurnPayload>();
    }
  });

  it("CronJobPatch.delivery allows partial and does not require mode", () => {
    expectTypeOf<CronJobPatch["delivery"]>().toEqualTypeOf<Partial<CronDelivery> | undefined>();
  });

  it("CronJob.failureAlert accepts false sentinel", () => {
    const job = {} as CronJob;
    expectTypeOf(job.failureAlert).extract<false>().toEqualTypeOf<false>();
  });
});
