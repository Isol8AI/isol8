import {
  defaultIssueFilterState,
  issueFilterArraysEqual,
  issueFilterLabel,
  issuePriorityOrder,
  issueQuickFilterPresets,
  issueStatusOrder,
  toggleIssueFilterValue,
  type IssueFilterState,
} from "@/components/teams/shared/lib/issueFilters";

describe("defaultIssueFilterState", () => {
  test("is fully empty / inactive", () => {
    expect(defaultIssueFilterState).toEqual({
      statuses: [],
      priorities: [],
      assignees: [],
      creators: [],
      labels: [],
      projects: [],
      workspaces: [],
      liveOnly: false,
      hideRoutineExecutions: false,
    } satisfies IssueFilterState);
  });
});

describe("issueFilterLabel", () => {
  test("title-cases snake_case statuses", () => {
    expect(issueFilterLabel("in_progress")).toBe("In Progress");
    expect(issueFilterLabel("blocked")).toBe("Blocked");
  });
});

describe("issueFilterArraysEqual", () => {
  test("treats order-independent arrays as equal", () => {
    expect(issueFilterArraysEqual(["a", "b"], ["b", "a"])).toBe(true);
  });

  test("treats different-length arrays as unequal", () => {
    expect(issueFilterArraysEqual(["a"], ["a", "b"])).toBe(false);
  });

  test("treats different-content arrays as unequal", () => {
    expect(issueFilterArraysEqual(["a", "b"], ["a", "c"])).toBe(false);
  });
});

describe("toggleIssueFilterValue", () => {
  test("adds when missing", () => {
    expect(toggleIssueFilterValue(["a"], "b")).toEqual(["a", "b"]);
  });

  test("removes when present", () => {
    expect(toggleIssueFilterValue(["a", "b"], "a")).toEqual(["b"]);
  });
});

describe("ordering + presets exported", () => {
  test("issueStatusOrder + issuePriorityOrder are non-empty", () => {
    expect(issueStatusOrder.length).toBeGreaterThan(0);
    expect(issuePriorityOrder.length).toBeGreaterThan(0);
  });

  test("issueQuickFilterPresets includes the 'All' preset with empty statuses", () => {
    const all = issueQuickFilterPresets.find((p) => p.label === "All");
    expect(all).toBeDefined();
    expect(all?.statuses).toEqual([]);
  });
});
