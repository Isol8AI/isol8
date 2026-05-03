// Test for InboxPanel.
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const mockPost = vi.fn();
const mockMutate = vi.fn();
const mockRead = vi.fn(() => ({
  data: {
    items: [
      { id: "i1", type: "agent_message", title: "New message from Alice" },
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

import { InboxPanel } from "@/components/teams/panels/InboxPanel";

describe("InboxPanel", () => {
  it("renders inbox items", () => {
    render(<InboxPanel />);
    expect(screen.getByText("Inbox")).toBeInTheDocument();
    expect(screen.getByText("New message from Alice")).toBeInTheDocument();
  });

  it("dismiss posts to /inbox/{id}/dismiss with empty body", async () => {
    mockPost.mockResolvedValue({});
    render(<InboxPanel />);

    fireEvent.click(screen.getByText("Dismiss"));
    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith("/inbox/i1/dismiss", {});
    });
  });
});
