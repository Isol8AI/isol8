// Test for IssuesPanel.
//
// Asserts the create-issue body uses ONLY whitelisted fields from
// CreateIssueBody (title, description, project_id, assignee_agent_id,
// priority). Extra fields would 422 at the BFF (extra="forbid").
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const mockPost = vi.fn();
const mockMutate = vi.fn();
const mockRead = vi.fn(() => ({
  data: { issues: [] },
  isLoading: false,
  error: null,
  mutate: mockMutate,
}));

vi.mock("@/hooks/useTeamsApi", () => ({
  useTeamsApi: () => ({
    read: mockRead,
    post: mockPost,
    patch: vi.fn(),
    del: vi.fn(),
  }),
}));

import { IssuesPanel } from "@/components/teams/panels/IssuesPanel";

describe("IssuesPanel", () => {
  it("renders empty state", () => {
    render(<IssuesPanel />);
    expect(screen.getByText("Issues")).toBeInTheDocument();
    expect(screen.getByText("No issues yet.")).toBeInTheDocument();
  });

  it("create form posts ONLY whitelisted fields (no smuggled fields)", async () => {
    mockPost.mockResolvedValue({ id: "i1" });
    render(<IssuesPanel />);

    fireEvent.click(screen.getByText("New issue"));
    fireEvent.change(screen.getByLabelText("Title"), {
      target: { value: "Fix bug" },
    });
    fireEvent.change(screen.getByLabelText("Priority"), {
      target: { value: "high" },
    });
    fireEvent.click(screen.getByText("Create"));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledTimes(1);
    });
    expect(mockPost).toHaveBeenCalledWith("/issues", {
      title: "Fix bug",
      priority: "high",
    });

    const [, body] = mockPost.mock.calls[0];
    const allowedKeys = new Set([
      "title",
      "description",
      "project_id",
      "assignee_agent_id",
      "priority",
    ]);
    for (const k of Object.keys(body as Record<string, unknown>)) {
      expect(allowedKeys.has(k)).toBe(true);
    }
    expect(body).not.toHaveProperty("adapterType");
    expect(body).not.toHaveProperty("adapterConfig");
    expect(body).not.toHaveProperty("status");
  });

  it("title-only submit posts only {title}", async () => {
    mockPost.mockResolvedValue({ id: "i2" });
    render(<IssuesPanel />);

    fireEvent.click(screen.getByText("New issue"));
    fireEvent.change(screen.getByLabelText("Title"), {
      target: { value: "Just a title" },
    });
    fireEvent.click(screen.getByText("Create"));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith("/issues", {
        title: "Just a title",
      });
    });
  });
});
