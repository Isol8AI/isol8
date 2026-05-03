// Test for GoalsPanel — confirms tree rendering and create body matches
// CreateGoalBody (title, description?, parent_id?).
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const mockPost = vi.fn();
const mockMutate = vi.fn();
const mockRead = vi.fn(() => ({
  data: {
    goals: [
      { id: "g1", title: "Top goal", parent_id: null },
      { id: "g2", title: "Sub goal", parent_id: "g1" },
    ],
  },
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

import { GoalsPanel } from "@/components/teams/panels/GoalsPanel";

describe("GoalsPanel", () => {
  it("renders tree-style goals", () => {
    render(<GoalsPanel />);
    expect(screen.getByText("Top goal")).toBeInTheDocument();
    expect(screen.getByText("Sub goal")).toBeInTheDocument();
  });

  it("create form posts only whitelisted fields", async () => {
    mockPost.mockResolvedValue({ id: "g3" });
    render(<GoalsPanel />);

    fireEvent.click(screen.getByText("New goal"));
    fireEvent.change(screen.getByLabelText("Title"), {
      target: { value: "New goal" },
    });
    fireEvent.click(screen.getByText("Create"));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith("/goals", { title: "New goal" });
    });
    const [, body] = mockPost.mock.calls[0];
    const allowed = new Set(["title", "description", "parent_id"]);
    for (const k of Object.keys(body as Record<string, unknown>)) {
      expect(allowed.has(k)).toBe(true);
    }
  });
});
