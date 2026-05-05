import { test, expect } from "vitest";
import type {
  Issue,
  Approval,
  HeartbeatRun,
  IssueComment,
  IssueCreateInput,
  IssueUpdateInput,
} from "@/components/teams/shared/types";
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

test("IssueComment type allows required + optional fields", () => {
  const c: IssueComment = { id: "c1", body: "Hello", createdAt: "2026-05-05T00:00:00Z" };
  expect(c.id).toBe("c1");
});

test("IssueCreateInput requires only title", () => {
  const input: IssueCreateInput = { title: "Fix bug" };
  expect(input.title).toBe("Fix bug");
});

test("IssueUpdateInput allows all-optional fields", () => {
  const input: IssueUpdateInput = {};
  expect(Object.keys(input).length).toBe(0);
});
