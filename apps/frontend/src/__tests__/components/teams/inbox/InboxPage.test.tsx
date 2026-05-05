// Smoke tests for InboxPage — verifies the full assembly: skeleton on initial
// load, empty-state copy per tab, list rendering when issues exist, and the
// tab-switch -> empty-state-copy plumbing. Hooks are mocked at the module
// boundary so we don't drag SWR/cache wiring into the page-level test.

import { describe, test, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

vi.mock("@/components/teams/inbox/hooks/useInboxData", () => ({
  useInboxData: vi.fn(),
}));
vi.mock("@/components/teams/inbox/hooks/useInboxKeyboardNav", () => ({
  useInboxKeyboardNav: vi.fn(),
}));
vi.mock("@/components/teams/inbox/hooks/useInboxArchiveStack", () => ({
  useInboxArchiveStack: vi.fn(),
}));
vi.mock("@/components/teams/inbox/hooks/useReadInboxItems", () => ({
  useReadInboxItems: vi.fn(),
}));

import { InboxPage } from "@/components/teams/inbox/InboxPage";
import { useInboxData } from "@/components/teams/inbox/hooks/useInboxData";
import { useInboxArchiveStack } from "@/components/teams/inbox/hooks/useInboxArchiveStack";
import { useReadInboxItems } from "@/components/teams/inbox/hooks/useReadInboxItems";
import type { Issue } from "@/components/teams/shared/types";

function makeIssue(overrides: Partial<Issue> = {}): Issue {
  return {
    id: "iss_1",
    title: "Test issue",
    status: "todo",
    identifier: "PAP-1",
    updatedAt: new Date().toISOString(),
    ...overrides,
  };
}

const baseProps = {
  companyId: "co_1",
  currentUserId: "u_1",
};

beforeEach(() => {
  vi.mocked(useInboxData).mockReturnValue({
    mineIssues: [],
    touchedIssues: [],
    allIssues: [],
    isLoading: false,
    isError: false,
    error: null,
  });
  vi.mocked(useInboxArchiveStack).mockReturnValue({
    archivingIssueIds: new Set(),
    hasUndoableArchive: false,
    archive: vi.fn().mockResolvedValue(undefined),
    undoArchive: vi.fn().mockResolvedValue(undefined),
    markRead: vi.fn().mockResolvedValue(undefined),
    markUnread: vi.fn().mockResolvedValue(undefined),
  });
  vi.mocked(useReadInboxItems).mockReturnValue({
    readItemKeys: new Set(),
    isRead: () => false,
    markRead: vi.fn(),
    markUnread: vi.fn(),
    markManyRead: vi.fn(),
    clearAll: vi.fn(),
  });
});

describe("InboxPage", () => {
  test("renders skeleton while initially loading with no sections", () => {
    vi.mocked(useInboxData).mockReturnValue({
      mineIssues: [],
      touchedIssues: [],
      allIssues: [],
      isLoading: true,
      isError: false,
      error: null,
    });
    render(<InboxPage {...baseProps} />);
    expect(
      document.querySelector("[data-testid='page-skeleton']"),
    ).not.toBeNull();
  });

  test("renders 'Inbox zero.' empty state on mine tab when there are no issues", () => {
    render(<InboxPage {...baseProps} />);
    expect(screen.getByText(/inbox zero/i)).toBeInTheDocument();
  });

  test("clicking the unread tab swaps the empty-state copy", () => {
    render(<InboxPage {...baseProps} />);
    fireEvent.click(screen.getByRole("tab", { name: /unread/i }));
    expect(screen.getByText(/no new inbox items/i)).toBeInTheDocument();
  });

  test("clicking the recent tab swaps the empty-state copy", () => {
    render(<InboxPage {...baseProps} />);
    fireEvent.click(screen.getByRole("tab", { name: /recent/i }));
    expect(screen.getByText(/no recent inbox items/i)).toBeInTheDocument();
  });

  test("renders InboxList rows when the active tab has issues", () => {
    vi.mocked(useInboxData).mockReturnValue({
      mineIssues: [makeIssue({ id: "iss_1" })],
      touchedIssues: [],
      allIssues: [],
      isLoading: false,
      isError: false,
      error: null,
    });
    const { container } = render(<InboxPage {...baseProps} />);
    expect(
      container.querySelector("[data-inbox-item-id='iss_1']"),
    ).not.toBeNull();
    // Empty-state copy should NOT be visible.
    expect(screen.queryByText(/inbox zero/i)).not.toBeInTheDocument();
  });

  test("typing in search shows the no-search-match empty state", () => {
    vi.mocked(useInboxData).mockReturnValue({
      mineIssues: [makeIssue({ id: "iss_1", title: "Apples" })],
      touchedIssues: [],
      allIssues: [],
      isLoading: false,
      isError: false,
      error: null,
    });
    render(<InboxPage {...baseProps} />);
    // Both the mobile + desktop search input render with data-page-search.
    const searchInput = document.querySelector(
      "input[data-page-search]",
    ) as HTMLInputElement;
    fireEvent.change(searchInput, { target: { value: "zzzzzz" } });
    expect(
      screen.getByText(/no inbox items match your search/i),
    ).toBeInTheDocument();
  });

  test("Mark all as read button is disabled when there are no unread items", () => {
    vi.mocked(useInboxData).mockReturnValue({
      mineIssues: [makeIssue({ id: "iss_1", unread: false })],
      touchedIssues: [],
      allIssues: [],
      isLoading: false,
      isError: false,
      error: null,
    });
    render(<InboxPage {...baseProps} />);
    expect(
      screen.getByRole("button", { name: /mark all as read/i }),
    ).toBeDisabled();
  });

  test("Mark all as read button is enabled when there are unread items", () => {
    vi.mocked(useInboxData).mockReturnValue({
      mineIssues: [makeIssue({ id: "iss_1", unread: true })],
      touchedIssues: [],
      allIssues: [],
      isLoading: false,
      isError: false,
      error: null,
    });
    render(<InboxPage {...baseProps} />);
    expect(
      screen.getByRole("button", { name: /mark all as read/i }),
    ).not.toBeDisabled();
  });
});
