// Smoke tests for InboxList — section headers, row rendering, click → onSelect,
// archiving fade-out class, isMobile SwipeToArchive wrapping, and empty list.

import { describe, test, expect, vi, beforeEach } from "vitest";
import { render, fireEvent, screen } from "@testing-library/react";
import { InboxList } from "@/components/teams/inbox/InboxList";
import type { InboxGroupedSection } from "@/components/teams/shared/lib/inbox";
import type { Issue } from "@/components/teams/shared/types";

function makeIssue(overrides: Partial<Issue> = {}): Issue {
  return {
    id: "iss_1",
    title: "Test issue",
    status: "todo",
    identifier: "PAP-1",
    updatedAt: "2026-05-05T00:00:00Z",
    ...overrides,
  };
}

const baseProps = {
  selectedIssueId: null,
  onSelect: vi.fn(),
  onOpen: vi.fn(),
  onArchive: vi.fn(),
  onMarkRead: vi.fn(),
  archivingIds: new Set<string>(),
  searchQuery: "",
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("InboxList", () => {
  test("renders 'Today' header for today section", () => {
    const sections: InboxGroupedSection[] = [
      { kind: "today", items: [{ kind: "issue", issue: makeIssue() }] },
    ];
    render(<InboxList {...baseProps} sections={sections} />);
    expect(screen.getByText("Today")).toBeInTheDocument();
  });

  test("renders 'Earlier' header for earlier section", () => {
    const sections: InboxGroupedSection[] = [
      { kind: "earlier", items: [{ kind: "issue", issue: makeIssue() }] },
    ];
    render(<InboxList {...baseProps} sections={sections} />);
    expect(screen.getByText("Earlier")).toBeInTheDocument();
  });

  test("renders 'Search results' header for search section", () => {
    const sections: InboxGroupedSection[] = [
      { kind: "search", items: [{ kind: "issue", issue: makeIssue() }] },
    ];
    render(
      <InboxList {...baseProps} sections={sections} searchQuery="fix" />,
    );
    expect(screen.getByText(/search/i)).toBeInTheDocument();
  });

  test("renders all rows across sections", () => {
    const sections: InboxGroupedSection[] = [
      {
        kind: "today",
        items: [
          { kind: "issue", issue: makeIssue({ id: "1", identifier: "PAP-1" }) },
          { kind: "issue", issue: makeIssue({ id: "2", identifier: "PAP-2" }) },
        ],
      },
      {
        kind: "earlier",
        items: [
          { kind: "issue", issue: makeIssue({ id: "3", identifier: "PAP-3" }) },
        ],
      },
    ];
    const { container } = render(
      <InboxList {...baseProps} sections={sections} />,
    );
    expect(
      container.querySelectorAll("[data-inbox-item-id]").length,
    ).toBe(3);
  });

  test("clicking a row fires onSelect with id", () => {
    const onSelect = vi.fn();
    const sections: InboxGroupedSection[] = [
      {
        kind: "today",
        items: [{ kind: "issue", issue: makeIssue({ id: "iss_1" }) }],
      },
    ];
    const { container } = render(
      <InboxList
        {...baseProps}
        sections={sections}
        onSelect={onSelect}
      />,
    );
    const wrapper = container.querySelector(
      '[data-inbox-item-id="iss_1"]',
    )!;
    fireEvent.click(wrapper);
    expect(onSelect).toHaveBeenCalledWith("iss_1");
  });

  test("archivingIds applies fade-out class", () => {
    const sections: InboxGroupedSection[] = [
      {
        kind: "today",
        items: [{ kind: "issue", issue: makeIssue({ id: "iss_1" }) }],
      },
    ];
    const { container } = render(
      <InboxList
        {...baseProps}
        sections={sections}
        archivingIds={new Set(["iss_1"])}
      />,
    );
    const wrapper = container.querySelector(
      '[data-inbox-item-id="iss_1"]',
    )!;
    expect(wrapper.className).toMatch(/opacity-0|translate-x|scale-/);
  });

  test("isMobile=true wraps rows in SwipeToArchive", () => {
    const sections: InboxGroupedSection[] = [
      { kind: "today", items: [{ kind: "issue", issue: makeIssue() }] },
    ];
    const { container } = render(
      <InboxList {...baseProps} sections={sections} isMobile={true} />,
    );
    // SwipeToArchive renders an inner element with `data-inbox-row-surface`.
    expect(
      container.querySelector("[data-inbox-row-surface]"),
    ).not.toBeNull();
  });

  test("isMobile=false renders rows without SwipeToArchive wrapper", () => {
    const sections: InboxGroupedSection[] = [
      { kind: "today", items: [{ kind: "issue", issue: makeIssue() }] },
    ];
    const { container } = render(
      <InboxList {...baseProps} sections={sections} />,
    );
    expect(container.querySelector("[data-inbox-row-surface]")).toBeNull();
  });

  test("empty sections list renders nothing meaningful", () => {
    const { container } = render(
      <InboxList {...baseProps} sections={[]} />,
    );
    expect(
      container.querySelectorAll("[data-inbox-item-id]").length,
    ).toBe(0);
  });

  test("non-issue work items are skipped defensively", () => {
    // Cast through unknown so the test exercises the defensive filter without
    // tripping the discriminated-union type guard.
    const sections = [
      {
        kind: "today",
        items: [
          { kind: "issue", issue: makeIssue({ id: "ok" }) },
          { kind: "approval", approval: { id: "a1", status: "pending" } },
        ],
      },
    ] as unknown as InboxGroupedSection[];
    const { container } = render(
      <InboxList {...baseProps} sections={sections} />,
    );
    expect(
      container.querySelectorAll("[data-inbox-item-id]").length,
    ).toBe(1);
  });
});
