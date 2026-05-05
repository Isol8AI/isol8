import { test, expect } from "vitest";
import type { Issue, Approval, HeartbeatRun } from "@/components/teams/shared/types";
import { ISSUE_STATUSES } from "@/components/teams/shared/types";

test("types module exports the runtime status list", () => {
  expect(ISSUE_STATUSES).toContain("todo");
  expect(ISSUE_STATUSES.length).toBeGreaterThan(5);
});

test("Issue type allows minimum-shape construction", () => {
  const issue: Issue = { id: "i1", title: "x", status: "todo" };
  expect(issue.id).toBe("i1");
});

test("Approval and HeartbeatRun discriminator unions compile", () => {
  const a: Approval = { id: "a1", status: "pending" };
  const r: HeartbeatRun = { id: "r1", status: "queued" };
  expect(a.status).toBe("pending");
  expect(r.status).toBe("queued");
});
