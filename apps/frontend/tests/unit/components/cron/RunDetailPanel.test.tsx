import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import type { CronJob, CronRunEntry } from "@/components/control/panels/cron/types";

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

import { RunDetailPanel } from "@/components/control/panels/cron/RunDetailPanel";

const baseJob: CronJob = {
  id: "job-1",
  name: "Daily digest",
  enabled: true,
  createdAtMs: 1_700_000_000_000,
  updatedAtMs: 1_700_000_000_000,
  schedule: { kind: "cron", expr: "0 7 * * *" },
  sessionTarget: "isolated",
  wakeMode: "next-heartbeat",
  payload: { kind: "agentTurn", message: "Summarize news" },
  state: { nextRunAtMs: 1_700_000_900_000 },
};

const baseRun: CronRunEntry = {
  jobId: "job-1",
  triggeredAtMs: 1_700_000_100_000,
  completedAtMs: 1_700_000_105_000,
  status: "ok",
  durationMs: 5000,
  sessionKey: "session-abc",
  sessionId: "session-abc-0000-0000",
  model: "sonnet-4",
  provider: "bedrock",
  usage: { input_tokens: 100, output_tokens: 50 },
  deliveryStatus: "delivered",
};

beforeEach(() => {
  rpcState.data = undefined;
  rpcState.error = null;
  rpcState.isLoading = false;
  rpcState.mutate = vi.fn();
});

describe("RunDetailPanel", () => {
  it("renders status, time, action buttons, and metadata", () => {
    render(
      <RunDetailPanel
        run={baseRun}
        job={baseJob}
        onClose={vi.fn()}
        onRunNow={vi.fn()}
        onEdit={vi.fn()}
      />,
    );
    // Status pill
    expect(screen.getByText("ok")).toBeInTheDocument();
    // Action buttons present
    expect(screen.getByRole("button", { name: /run now/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /edit job/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /copy prompt/i })).toBeInTheDocument();
    // Metadata rows
    expect(screen.getByText("Model")).toBeInTheDocument();
    expect(screen.getByText(/sonnet-4.*bedrock/)).toBeInTheDocument();
    expect(screen.getByText("Tokens")).toBeInTheDocument();
    expect(screen.getByText("Delivery")).toBeInTheDocument();
    expect(screen.getByText(/delivered/i)).toBeInTheDocument();
  });

  it("renders an error banner when status is error", () => {
    render(
      <RunDetailPanel
        run={{ ...baseRun, status: "error", error: "timeout" }}
        job={baseJob}
        onClose={vi.fn()}
        onRunNow={vi.fn()}
        onEdit={vi.fn()}
      />,
    );
    expect(screen.getByText(/run failed/i)).toBeInTheDocument();
    expect(screen.getByText("timeout")).toBeInTheDocument();
  });

  it("invokes onClose, onRunNow, onEdit when buttons clicked", () => {
    const onClose = vi.fn();
    const onRunNow = vi.fn();
    const onEdit = vi.fn();
    render(
      <RunDetailPanel
        run={baseRun}
        job={baseJob}
        onClose={onClose}
        onRunNow={onRunNow}
        onEdit={onEdit}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /run now/i }));
    fireEvent.click(screen.getByRole("button", { name: /edit job/i }));
    // The X button has no accessible name; pick the last plain button in the header.
    const closeBtn = screen
      .getAllByRole("button")
      .find((b) => b.querySelector("svg.lucide-x"));
    if (closeBtn) fireEvent.click(closeBtn);
    expect(onRunNow).toHaveBeenCalledTimes(1);
    expect(onEdit).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("toggles the prompt accordion and shows the job payload message when no transcript user message", () => {
    // No transcript data -> falls back to job.payload.message
    render(
      <RunDetailPanel
        run={baseRun}
        job={baseJob}
        onClose={vi.fn()}
        onRunNow={vi.fn()}
        onEdit={vi.fn()}
      />,
    );
    const toggle = screen.getByRole("button", { name: /^prompt/i });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    // Payload message is shown because transcript is empty
    expect(screen.getByText("Summarize news")).toBeInTheDocument();
  });

  it("shows 'job edited since this run' when job updatedAt > run triggeredAt and no transcript user message", () => {
    render(
      <RunDetailPanel
        run={baseRun}
        job={{ ...baseJob, updatedAtMs: baseRun.triggeredAtMs + 10_000 }}
        onClose={vi.fn()}
        onRunNow={vi.fn()}
        onEdit={vi.fn()}
      />,
    );
    expect(screen.getByText(/job edited since this run/i)).toBeInTheDocument();
  });

  it("uses first user message from transcript as prompt when available", () => {
    rpcState.data = {
      messages: [
        {
          role: "user",
          ts: baseRun.triggeredAtMs + 500,
          content: [{ type: "text", text: "original prompt here" }],
        },
        {
          role: "assistant",
          ts: baseRun.triggeredAtMs + 1000,
          content: [{ type: "text", text: "answer" }],
        },
      ],
    };
    render(
      <RunDetailPanel
        run={baseRun}
        job={{ ...baseJob, updatedAtMs: baseRun.triggeredAtMs + 10_000 }}
        onClose={vi.fn()}
        onRunNow={vi.fn()}
        onEdit={vi.fn()}
      />,
    );
    // Expand prompt accordion
    fireEvent.click(screen.getByRole("button", { name: /^prompt/i }));
    // The text appears twice — once in the accordion, once in the transcript.
    expect(screen.getAllByText("original prompt here").length).toBeGreaterThanOrEqual(1);
    // No "edited since" chip because transcript provided the prompt
    expect(
      screen.queryByText(/job edited since this run/i),
    ).not.toBeInTheDocument();
  });
});
