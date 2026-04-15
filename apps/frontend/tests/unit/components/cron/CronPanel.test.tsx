import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { CronPanel } from "@/components/control/panels/CronPanel";

// Mock useGatewayRpc — cron.list returns one job, cron.runs returns one run.
vi.mock("@/hooks/useGatewayRpc", () => {
  const sampleJob = {
    id: "job-1",
    name: "Daily digest",
    enabled: true,
    createdAtMs: 1_700_000_000_000,
    updatedAtMs: 1_700_000_000_000,
    schedule: { kind: "cron", expr: "0 7 * * *", tz: "UTC" },
    sessionTarget: "isolated",
    wakeMode: "next-heartbeat",
    payload: { kind: "agentTurn", message: "Summarize news" },
    state: { lastRunStatus: "ok" },
  };
  const sampleRun = {
    jobId: "job-1",
    triggeredAtMs: 1_700_000_100_000,
    status: "ok",
    durationMs: 12_000,
    summary: "Sample run output",
  };
  return {
    useGatewayRpc: (method: string | null) => {
      if (method === "cron.list") {
        return { data: { jobs: [sampleJob] }, error: null, isLoading: false, mutate: vi.fn() };
      }
      if (method === "cron.runs") {
        return { data: { entries: [sampleRun] }, error: null, isLoading: false, mutate: vi.fn() };
      }
      return { data: null, error: null, isLoading: false, mutate: vi.fn() };
    },
    useGatewayRpcMutation: () => ({
      trigger: vi.fn().mockResolvedValue({}),
      isMutating: false,
    }),
  };
});

describe("CronPanel ViewState", () => {
  it("starts in overview state showing jobs list", () => {
    render(<CronPanel />);
    expect(screen.getByText("Daily digest")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /back to jobs/i })).not.toBeInTheDocument();
  });

  it("transitions to runs state when a run row is clicked", () => {
    render(<CronPanel />);
    // Expand the job card to reveal the recent runs list
    fireEvent.click(screen.getByText("Daily digest"));
    // Click the run row (the status badge label or the summary is discoverable)
    const runRow = screen.getByText("Sample run output").closest('[role="button"], button, [role="row"]');
    if (!runRow) {
      // Fall back to clicking the summary span's parent
      fireEvent.click(screen.getByText("Sample run output"));
    } else {
      fireEvent.click(runRow as HTMLElement);
    }
    // Assert State B markers
    expect(screen.getByRole("button", { name: /back to jobs/i })).toBeInTheDocument();
    // The jobs list headline should be gone (no more JobList in render tree)
    expect(screen.queryByRole("button", { name: /^new cron$/i })).not.toBeInTheDocument();
  });

  it("returns to overview when Back to jobs is clicked", () => {
    render(<CronPanel />);
    fireEvent.click(screen.getByText("Daily digest"));
    fireEvent.click(screen.getByText("Sample run output"));
    fireEvent.click(screen.getByRole("button", { name: /back to jobs/i }));
    expect(screen.getByText("Daily digest")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /back to jobs/i })).not.toBeInTheDocument();
  });
});
