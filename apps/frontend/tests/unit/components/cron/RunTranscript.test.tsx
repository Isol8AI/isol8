import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

// State the mock holds between tests; test bodies tweak before rendering.
const rpcState: {
  data: unknown;
  error: Error | null;
  isLoading: boolean;
  mutate: ReturnType<typeof vi.fn>;
} = {
  data: undefined,
  error: null,
  isLoading: false,
  mutate: vi.fn(),
};

vi.mock("@/hooks/useGatewayRpc", () => ({
  useGatewayRpc: () => rpcState,
  useGatewayRpcMutation: () => vi.fn(),
}));

import { RunTranscript } from "@/components/control/panels/cron/RunTranscript";

beforeEach(() => {
  rpcState.data = undefined;
  rpcState.error = null;
  rpcState.isLoading = false;
  rpcState.mutate = vi.fn();
});

describe("RunTranscript", () => {
  it("renders a 'no transcript' message when sessionKey is undefined", () => {
    render(<RunTranscript sessionKey={undefined} />);
    expect(screen.getByText(/no transcript available/i)).toBeInTheDocument();
  });

  it("renders transcript text when RPC returns messages", () => {
    rpcState.data = {
      messages: [
        { role: "user", content: [{ type: "text", text: "What's the weather?" }] },
        { role: "assistant", content: [{ type: "text", text: "Sunny and warm." }] },
      ],
    };
    render(<RunTranscript sessionKey="session-abc" />);
    expect(screen.getByText("What's the weather?")).toBeInTheDocument();
    expect(screen.getByText("Sunny and warm.")).toBeInTheDocument();
  });

  it("renders a loading state when isLoading is true", () => {
    rpcState.isLoading = true;
    render(<RunTranscript sessionKey="session-abc" />);
    expect(screen.getByText(/loading transcript/i)).toBeInTheDocument();
  });

  it("renders an error banner with a Retry button when RPC errors", () => {
    rpcState.error = new Error("boom");
    render(<RunTranscript sessionKey="session-abc" />);
    expect(screen.getByText(/transcript unavailable/i)).toBeInTheDocument();
    const retry = screen.getByRole("button", { name: /retry/i });
    fireEvent.click(retry);
    expect(rpcState.mutate).toHaveBeenCalledTimes(1);
  });

  it("falls back to 'no transcript' when RPC returns zero messages", () => {
    rpcState.data = { messages: [] };
    render(<RunTranscript sessionKey="session-abc" />);
    expect(screen.getByText(/no transcript available/i)).toBeInTheDocument();
  });
});
