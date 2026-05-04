import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { InviteTeammatesStep } from "../InviteTeammatesStep";

const mockPost = vi.fn();
vi.mock("@/lib/api", () => ({
  useApi: () => ({ post: mockPost }),
}));

describe("InviteTeammatesStep", () => {
  beforeEach(() => {
    mockPost.mockReset();
  });

  it("posts to /orgs/{org_id}/invitations with email and role", async () => {
    mockPost.mockResolvedValueOnce({ invitation_id: "orginv_1" });
    const onComplete = vi.fn();
    render(<InviteTeammatesStep orgId="org_test" onComplete={onComplete} />);

    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "teammate@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send invite/i }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith(
        "/orgs/org_test/invitations",
        expect.objectContaining({
          email: "teammate@example.com",
          role: "org:member",
        }),
      );
    });
  });

  it("renders the 409 personal_user_exists message inline", async () => {
    mockPost.mockRejectedValueOnce({
      status: 409,
      body: {
        detail: {
          code: "personal_user_exists",
          message:
            "subscriber@example.com already has an active personal Isol8 subscription. They must cancel it before they can be invited to an organization.",
        },
      },
    });
    render(<InviteTeammatesStep orgId="org_test" onComplete={vi.fn()} />);

    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "subscriber@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send invite/i }));

    expect(
      await screen.findByText(/already has an active personal Isol8 subscription/i),
    ).toBeInTheDocument();
  });

  it("calls onComplete when 'Done' is clicked", () => {
    const onComplete = vi.fn();
    render(<InviteTeammatesStep orgId="org_test" onComplete={onComplete} />);
    fireEvent.click(screen.getByRole("button", { name: /done/i }));
    expect(onComplete).toHaveBeenCalled();
  });
});
