// @vitest-environment jsdom
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ChannelSetupStep } from "@/components/chat/ChannelSetupStep";

vi.mock("@/hooks/useGatewayRpc", () => ({
  useGatewayRpc: () => ({
    data: { hash: "abc123", config: {}, valid: true, path: "", exists: true, raw: "{}" },
    error: undefined,
    isLoading: false,
    mutate: vi.fn(),
  }),
  useGatewayRpcMutation: () => vi.fn().mockResolvedValue({}),
}));

describe("ChannelSetupStep", () => {
  it("renders all three channel accordions", () => {
    render(<ChannelSetupStep onComplete={vi.fn()} />);
    expect(screen.getByText("Telegram")).toBeInTheDocument();
    expect(screen.getByText("WhatsApp")).toBeInTheDocument();
    expect(screen.getByText("Discord")).toBeInTheDocument();
  });

  it("shows Skip link and disabled Continue button initially", () => {
    render(<ChannelSetupStep onComplete={vi.fn()} />);
    expect(screen.getByText("Skip")).toBeInTheDocument();
    const continueButton = screen.getByRole("button", { name: /continue/i });
    expect(continueButton).toBeDisabled();
  });

  it("calls onComplete when Skip is clicked", () => {
    const onComplete = vi.fn();
    render(<ChannelSetupStep onComplete={onComplete} />);
    fireEvent.click(screen.getByText("Skip"));
    expect(onComplete).toHaveBeenCalledTimes(1);
  });

  it("expands Telegram accordion on click and shows Bot Token field", () => {
    render(<ChannelSetupStep onComplete={vi.fn()} />);
    // Initially Bot Token label should not be visible
    expect(screen.queryByText("Bot Token")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Telegram"));
    expect(screen.getByText("Bot Token")).toBeInTheDocument();
  });

  it("shows QR button when WhatsApp is expanded", () => {
    render(<ChannelSetupStep onComplete={vi.fn()} />);
    fireEvent.click(screen.getByText("WhatsApp"));
    expect(screen.getByRole("button", { name: /show qr code/i })).toBeInTheDocument();
  });
});
