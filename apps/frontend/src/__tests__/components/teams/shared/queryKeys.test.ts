import { describe, test, expect } from "vitest";
import { teamsQueryKeys } from "@/components/teams/shared/queryKeys";

describe("teamsQueryKeys", () => {
  test("inbox.list builds a path with tab + filter query string", () => {
    const key = teamsQueryKeys.inbox.list("mine", { status: "todo", search: "fix" });
    expect(key).toBe("/teams/inbox?tab=mine&status=todo&search=fix");
  });

  test("inbox.list with no filters omits empty filter args", () => {
    expect(teamsQueryKeys.inbox.list("all", {})).toBe("/teams/inbox?tab=all");
  });

  test("inbox.list serializes filter values url-encoded", () => {
    expect(teamsQueryKeys.inbox.list("mine", { search: "fix bug" })).toBe(
      "/teams/inbox?tab=mine&search=fix%20bug"
    );
  });

  test("issues.detail and approvals.detail build per-id keys", () => {
    expect(teamsQueryKeys.issues.detail("iss_1")).toBe("/teams/issues/iss_1");
    expect(teamsQueryKeys.approvals.detail("a1")).toBe("/teams/approvals/a1");
  });

  test("inbox.approvals + inbox.runs + inbox.liveRuns return fixed keys", () => {
    expect(teamsQueryKeys.inbox.approvals()).toBe("/teams/inbox/approvals");
    expect(teamsQueryKeys.inbox.runs()).toBe("/teams/inbox/runs");
    expect(teamsQueryKeys.inbox.liveRuns()).toBe("/teams/inbox/live-runs");
  });
});
