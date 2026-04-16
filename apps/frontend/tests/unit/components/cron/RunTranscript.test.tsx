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

import { RunTranscript, firstUserMessage } from "@/components/control/panels/cron/RunTranscript";
import type { AdaptedMessage } from "@/components/control/panels/cron/sessionMessageAdapter";

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

describe("firstUserMessage", () => {
  it("returns the first user message overall when no afterTs is provided", () => {
    const messages: AdaptedMessage[] = [
      { id: "0", role: "user", content: "first prompt", ts: 1_000 },
      { id: "1", role: "assistant", content: "ack", ts: 2_000 },
      { id: "2", role: "user", content: "second prompt", ts: 3_000 },
    ];
    expect(firstUserMessage(messages)).toBe("first prompt");
  });

  it("skips user messages older than afterTs in multi-run sessions", () => {
    const messages: AdaptedMessage[] = [
      // Old run: well before the cutoff.
      { id: "0", role: "user", content: "old prompt", ts: 1_000 },
      { id: "1", role: "assistant", content: "old answer", ts: 1_500 },
      // Current run: at the cutoff.
      { id: "2", role: "user", content: "current prompt", ts: 100_000 },
      { id: "3", role: "assistant", content: "current answer", ts: 100_500 },
    ];
    expect(firstUserMessage(messages, 100_000)).toBe("current prompt");
  });

  it("returns undefined (not earliest) when no message has ts and afterTs is provided", () => {
    // Tighter semantics: when afterTs is provided but no message has a ts
    // satisfying the bound, we deliberately return undefined rather than
    // falling back to the first user message overall. The old fallback was
    // too permissive in shared-session reruns.
    const messages: AdaptedMessage[] = [
      { id: "0", role: "user", content: "no-ts prompt" },
      { id: "1", role: "assistant", content: "answer" },
    ];
    expect(firstUserMessage(messages, 100_000)).toBeUndefined();
  });

  it("returns undefined when no message is at-or-after afterTs", () => {
    const messages: AdaptedMessage[] = [
      { id: "0", role: "user", content: "stale prompt", ts: 1_000 },
      { id: "1", role: "assistant", content: "stale answer", ts: 1_500 },
    ];
    expect(firstUserMessage(messages, 100_000)).toBeUndefined();
  });

  it("rejects messages just before afterTs (no tolerance window)", () => {
    // With the old 5s tolerance this would have matched. With the tighter
    // semantics it must not — back-to-back manual reruns can otherwise
    // surface the previous run's prompt.
    const messages: AdaptedMessage[] = [
      { id: "0", role: "user", content: "previous run prompt", ts: 99_999 },
      { id: "1", role: "user", content: "current run prompt", ts: 100_000 },
    ];
    expect(firstUserMessage(messages, 100_000)).toBe("current run prompt");
  });

  it("excludes messages after beforeTs upper bound", () => {
    const messages: AdaptedMessage[] = [
      { id: "0", role: "user", content: "in-range prompt", ts: 100_500 },
      { id: "1", role: "user", content: "out-of-range prompt", ts: 200_000 },
    ];
    // afterTs=100_000, beforeTs=101_000 → only the in-range prompt qualifies.
    expect(firstUserMessage(messages, 100_000, 101_000)).toBe("in-range prompt");
  });

  it("returns undefined when only matches are after beforeTs", () => {
    const messages: AdaptedMessage[] = [
      { id: "0", role: "user", content: "next-run prompt", ts: 200_000 },
    ];
    expect(firstUserMessage(messages, 100_000, 101_000)).toBeUndefined();
  });
});
