import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";

import { BotSetupWizard } from "@/components/channels/BotSetupWizard";

const postMock = vi.fn();
const patchConfigMock = vi.fn();

vi.mock("@/lib/api", () => ({
  useApi: () => ({
    patchConfig: patchConfigMock,
    post: postMock,
  }),
}));

vi.mock("@/hooks/useGatewayRpc", () => ({
  useGatewayRpcMutation: () => vi.fn().mockResolvedValue({
    channelAccounts: { telegram: [{ connected: true }] },
  }),
}));

describe("BotSetupWizard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    patchConfigMock.mockResolvedValue({ status: "patched", owner_id: "user_test" });
    postMock.mockResolvedValue({ status: "linked", peer_id: "12345" });
  });

  it("shows the token paste step in create mode", () => {
    render(
      <BotSetupWizard
        mode="create"
        provider="telegram"
        agentId="main"
        onComplete={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.getByLabelText(/bot token/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /next/i })).toBeDisabled();
  });

  it("enables the next button once a token is typed", async () => {
    const user = userEvent.setup();
    render(
      <BotSetupWizard
        mode="create"
        provider="telegram"
        agentId="main"
        onComplete={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    await user.type(screen.getByLabelText(/bot token/i), "123:abcABC");
    expect(screen.getByRole("button", { name: /next/i })).toBeEnabled();
  });

  it("skips the token step in link-only mode", () => {
    render(
      <BotSetupWizard
        mode="link-only"
        provider="telegram"
        agentId="main"
        onComplete={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.queryByLabelText(/bot token/i)).not.toBeInTheDocument();
    expect(screen.getByLabelText(/pairing code/i)).toBeInTheDocument();
  });

  it("shows friendly message on 404 code not found", async () => {
    const err: Error & { status?: number } = new Error("not found");
    err.status = 404;
    postMock.mockRejectedValueOnce(err);

    render(
      <BotSetupWizard
        mode="link-only"
        provider="telegram"
        agentId="main"
        onComplete={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/pairing code/i), "BADCODE");
    await user.click(screen.getByRole("button", { name: /link/i }));
    await waitFor(() => {
      expect(screen.getByText(/code expired or not found/i)).toBeInTheDocument();
    });
  });

  it("shows friendly message on 409 peer already linked", async () => {
    const err: Error & { status?: number } = new Error("conflict");
    err.status = 409;
    postMock.mockRejectedValueOnce(err);

    render(
      <BotSetupWizard
        mode="link-only"
        provider="telegram"
        agentId="main"
        onComplete={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/pairing code/i), "ABC12345");
    await user.click(screen.getByRole("button", { name: /link/i }));
    await waitFor(() => {
      expect(screen.getByText(/already linked to another member/i)).toBeInTheDocument();
    });
  });

  it("shows TWO token fields plus a manifest block when provider is slack", () => {
    render(
      <BotSetupWizard
        mode="create"
        provider="slack"
        agentId="main"
        onComplete={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.getByLabelText(/app.level token/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/bot token/i)).toBeInTheDocument();
    // Manifest instructions visible
    expect(screen.getByText(/paste.*manifest/i)).toBeInTheDocument();
  });
});
