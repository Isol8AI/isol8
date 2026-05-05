import { describe, test, expect } from "vitest";
import {
  INBOX_MINE_ISSUE_STATUSES,
  INBOX_MINE_ISSUE_STATUS_FILTER,
  buildGroupedInboxSections,
  buildInboxKeyboardNavEntries,
  getInboxWorkItems,
  getRecentTouchedIssues,
  isMineInboxTab,
  matchesInboxIssueSearch,
  resolveInboxSelectionIndex,
  type InboxGroupedSection,
  type InboxWorkItem,
} from "@/components/teams/shared/lib/inbox";
import type { Issue } from "@/components/teams/shared/types";

function makeIssue(overrides: Partial<Issue> = {}): Issue {
  return {
    id: overrides.id ?? "issue-1",
    title: overrides.title ?? "Untitled",
    status: overrides.status ?? "todo",
    ...overrides,
  };
}

describe("INBOX_MINE_ISSUE_STATUS_FILTER", () => {
  test("is a comma-joined string of the mine statuses", () => {
    expect(INBOX_MINE_ISSUE_STATUS_FILTER).toBe(
      "backlog,todo,in_progress,in_review,blocked,done",
    );
  });

  test("matches the exported tuple", () => {
    expect(INBOX_MINE_ISSUE_STATUS_FILTER).toBe(
      INBOX_MINE_ISSUE_STATUSES.join(","),
    );
  });

  test("contains 'todo' so the BFF default mine query returns todos", () => {
    expect(INBOX_MINE_ISSUE_STATUS_FILTER.split(",")).toContain("todo");
  });
});

describe("getInboxWorkItems", () => {
  test("wraps each issue in {kind:'issue', issue}", () => {
    const i1 = makeIssue({ id: "a" });
    const i2 = makeIssue({ id: "b" });
    expect(getInboxWorkItems([i1, i2])).toEqual([
      { kind: "issue", issue: i1 },
      { kind: "issue", issue: i2 },
    ]);
  });

  test("returns empty array for empty input", () => {
    expect(getInboxWorkItems([])).toEqual([]);
  });

  test("preserves input order", () => {
    const issues = ["c", "a", "b"].map((id) => makeIssue({ id }));
    const ids = getInboxWorkItems(issues).map((item) => item.issue.id);
    expect(ids).toEqual(["c", "a", "b"]);
  });
});

describe("getRecentTouchedIssues", () => {
  test("returns all issues when unreadOnly is false / unset", () => {
    const issues = [
      makeIssue({ id: "1", unread: true }),
      makeIssue({ id: "2", unread: false }),
      makeIssue({ id: "3" }),
    ];
    expect(getRecentTouchedIssues(issues).map((i) => i.id)).toEqual([
      "1",
      "2",
      "3",
    ]);
  });

  test("filters by unread === true when unreadOnly is set", () => {
    const issues = [
      makeIssue({ id: "1", unread: true }),
      makeIssue({ id: "2", unread: false }),
      makeIssue({ id: "3", unread: null }),
      makeIssue({ id: "4" }),
    ];
    expect(
      getRecentTouchedIssues(issues, { unreadOnly: true }).map((i) => i.id),
    ).toEqual(["1"]);
  });

  test("does not mutate the input array", () => {
    const issues = [makeIssue({ id: "1" })];
    const out = getRecentTouchedIssues(issues);
    out.push(makeIssue({ id: "2" }));
    expect(issues).toHaveLength(1);
  });
});

describe("matchesInboxIssueSearch", () => {
  test("returns true on empty / whitespace query", () => {
    const i = makeIssue({ title: "Anything" });
    expect(matchesInboxIssueSearch(i, "")).toBe(true);
    expect(matchesInboxIssueSearch(i, "   ")).toBe(true);
  });

  test("matches title case-insensitively", () => {
    const i = makeIssue({ title: "Fix Inbox keyboard nav" });
    expect(matchesInboxIssueSearch(i, "fix")).toBe(true);
    expect(matchesInboxIssueSearch(i, "INBOX")).toBe(true);
    expect(matchesInboxIssueSearch(i, "ship")).toBe(false);
  });

  test("matches identifier when present", () => {
    const i = makeIssue({ title: "Whatever", identifier: "ENG-123" });
    expect(matchesInboxIssueSearch(i, "eng-123")).toBe(true);
    expect(matchesInboxIssueSearch(i, "eng-999")).toBe(false);
  });

  test("does not crash when identifier / title are missing-ish", () => {
    const i = makeIssue({ title: "", identifier: null });
    expect(matchesInboxIssueSearch(i, "foo")).toBe(false);
    expect(matchesInboxIssueSearch(i, "")).toBe(true);
  });
});

describe("buildGroupedInboxSections", () => {
  const NOW = "2026-05-04T15:00:00.000Z";

  test("returns empty sections for empty input", () => {
    expect(buildGroupedInboxSections([], { nowIso: NOW })).toEqual([]);
  });

  test("returns a single 'search' section when searchQuery is non-empty", () => {
    const items: InboxWorkItem[] = [
      { kind: "issue", issue: makeIssue({ id: "1" }) },
      { kind: "issue", issue: makeIssue({ id: "2" }) },
    ];
    const sections = buildGroupedInboxSections(items, {
      nowIso: NOW,
      searchQuery: "foo",
    });
    expect(sections).toHaveLength(1);
    expect(sections[0].kind).toBe("search");
    expect(sections[0].items).toHaveLength(2);
  });

  test("treats whitespace-only searchQuery as no search", () => {
    const items: InboxWorkItem[] = [
      {
        kind: "issue",
        issue: makeIssue({ id: "1", updatedAt: "2026-05-04T16:00:00.000Z" }),
      },
    ];
    const sections = buildGroupedInboxSections(items, {
      nowIso: NOW,
      searchQuery: "   ",
    });
    expect(sections.map((s) => s.kind)).toEqual(["today"]);
  });

  test("splits items into today vs earlier by updatedAt (rolling 24h window)", () => {
    // NOW = 2026-05-04T15:00:00Z → cutoff = 2026-05-03T15:00:00Z.
    // "today" = items strictly within the last 24h. TZ-agnostic.
    const items: InboxWorkItem[] = [
      {
        kind: "issue",
        issue: makeIssue({ id: "today-1", updatedAt: "2026-05-04T08:00:00.000Z" }),
      },
      {
        kind: "issue",
        issue: makeIssue({ id: "today-2", updatedAt: "2026-05-03T20:00:00.000Z" }),
      },
      // earlier (older than 24h from NOW)
      {
        kind: "issue",
        issue: makeIssue({ id: "old-1", updatedAt: "2026-05-03T10:00:00.000Z" }),
      },
      {
        kind: "issue",
        issue: makeIssue({ id: "old-2", updatedAt: "2026-04-01T08:00:00.000Z" }),
      },
    ];
    const sections = buildGroupedInboxSections(items, { nowIso: NOW });
    expect(sections.map((s) => s.kind)).toEqual(["today", "earlier"]);
    expect(sections[0].items.map((i) => i.issue.id)).toEqual([
      "today-1",
      "today-2",
    ]);
    expect(sections[1].items.map((i) => i.issue.id)).toEqual(["old-1", "old-2"]);
  });

  test("falls back to lastActivityAt when updatedAt missing", () => {
    const items: InboxWorkItem[] = [
      {
        kind: "issue",
        issue: makeIssue({
          id: "fallback",
          updatedAt: null,
          lastActivityAt: "2026-05-04T09:00:00.000Z",
        }),
      },
    ];
    const sections = buildGroupedInboxSections(items, { nowIso: NOW });
    expect(sections.map((s) => s.kind)).toEqual(["today"]);
  });

  test("omits empty sections", () => {
    const items: InboxWorkItem[] = [
      {
        kind: "issue",
        issue: makeIssue({ id: "1", updatedAt: "2026-05-04T10:00:00.000Z" }),
      },
    ];
    const sections = buildGroupedInboxSections(items, { nowIso: NOW });
    expect(sections.map((s) => s.kind)).toEqual(["today"]);
  });
});

describe("buildInboxKeyboardNavEntries", () => {
  test("flattens sections into [{id, kind}] preserving order", () => {
    const sections: InboxGroupedSection[] = [
      {
        kind: "today",
        items: [
          { kind: "issue", issue: makeIssue({ id: "a" }) },
          { kind: "issue", issue: makeIssue({ id: "b" }) },
        ],
      },
      {
        kind: "earlier",
        items: [{ kind: "issue", issue: makeIssue({ id: "c" }) }],
      },
    ];
    expect(buildInboxKeyboardNavEntries(sections)).toEqual([
      { id: "a", kind: "issue" },
      { id: "b", kind: "issue" },
      { id: "c", kind: "issue" },
    ]);
  });

  test("returns [] for empty sections", () => {
    expect(buildInboxKeyboardNavEntries([])).toEqual([]);
  });

  test("skips empty section.items", () => {
    const sections: InboxGroupedSection[] = [
      { kind: "today", items: [] },
      {
        kind: "earlier",
        items: [{ kind: "issue", issue: makeIssue({ id: "x" }) }],
      },
    ];
    expect(buildInboxKeyboardNavEntries(sections)).toEqual([
      { id: "x", kind: "issue" },
    ]);
  });
});

describe("resolveInboxSelectionIndex", () => {
  const navItems = [
    { id: "a", kind: "issue" as const },
    { id: "b", kind: "issue" as const },
    { id: "c", kind: "issue" as const },
  ];

  test("returns the index when selectedId is found", () => {
    expect(resolveInboxSelectionIndex(navItems, "a")).toBe(0);
    expect(resolveInboxSelectionIndex(navItems, "b")).toBe(1);
    expect(resolveInboxSelectionIndex(navItems, "c")).toBe(2);
  });

  test("returns -1 when selectedId is null", () => {
    expect(resolveInboxSelectionIndex(navItems, null)).toBe(-1);
  });

  test("returns -1 when selectedId is not in navItems", () => {
    expect(resolveInboxSelectionIndex(navItems, "missing")).toBe(-1);
  });

  test("returns -1 for empty navItems", () => {
    expect(resolveInboxSelectionIndex([], "a")).toBe(-1);
  });
});

describe("isMineInboxTab", () => {
  test("true for 'mine' only", () => {
    expect(isMineInboxTab("mine")).toBe(true);
    expect(isMineInboxTab("recent")).toBe(false);
    expect(isMineInboxTab("unread")).toBe(false);
    expect(isMineInboxTab("all")).toBe(false);
  });
});
