import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";

import { BotSetupWizard } from "@/components/channels/BotSetupWizard";

vi.mock("@/lib/api", () => ({
  useApi: () => ({
    patchConfig: vi.fn().mockResolvedValue({ status: "patched", owner_id: "user_test" }),
    post: vi.fn().mockResolvedValue({ status: "linked", peer_id: "12345" }),
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
});
