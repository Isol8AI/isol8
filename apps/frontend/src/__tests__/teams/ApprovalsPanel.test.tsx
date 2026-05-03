// Test for ApprovalsPanel.
//
// Confirms approve/reject post bodies contain ONLY the whitelisted fields
// (note for approve, reason for reject). Defense in depth — BFF would 422
// on smuggled fields via ApproveApprovalBody / RejectApprovalBody.
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const mockPost = vi.fn();
const mockMutate = vi.fn();
const mockRead = vi.fn(() => ({
  data: {
    approvals: [
      { id: "ap1", title: "Approve deploy", description: "main → prod" },
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

import { ApprovalsPanel } from "@/components/teams/panels/ApprovalsPanel";

describe("ApprovalsPanel", () => {
  beforeEach(() => {
    mockPost.mockReset();
  });

  it("approve posts ONLY {note}", async () => {
    mockPost.mockResolvedValue({});
    render(<ApprovalsPanel />);

    fireEvent.click(screen.getByText("Approve"));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledTimes(1);
    });
    expect(mockPost).toHaveBeenCalledWith("/approvals/ap1/approve", {
      note: "approved via UI",
    });
    const [, body] = mockPost.mock.calls[0];
    expect(Object.keys(body as Record<string, unknown>)).toEqual(["note"]);
  });

  it("reject prompts for reason and posts ONLY {reason}", async () => {
    const promptSpy = vi
      .spyOn(window, "prompt")
      .mockReturnValue("not safe to ship");
    mockPost.mockResolvedValue({});
    render(<ApprovalsPanel />);

    fireEvent.click(screen.getByText("Reject"));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledTimes(1);
    });
    expect(mockPost).toHaveBeenCalledWith("/approvals/ap1/reject", {
      reason: "not safe to ship",
    });
    const [, body] = mockPost.mock.calls[0];
    expect(Object.keys(body as Record<string, unknown>)).toEqual(["reason"]);

    promptSpy.mockRestore();
  });

  it("reject is no-op when user cancels prompt", async () => {
    const promptSpy = vi.spyOn(window, "prompt").mockReturnValue(null);
    render(<ApprovalsPanel />);

    fireEvent.click(screen.getByText("Reject"));
    expect(mockPost).not.toHaveBeenCalled();

    promptSpy.mockRestore();
  });
});
