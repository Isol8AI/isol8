import { render, screen, fireEvent, act, within } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { CronPanel } from "@/components/control/panels/CronPanel";
import { RunDetailPanel } from "@/components/control/panels/cron/RunDetailPanel";

// Hoisted test-controllable state so each test can set up a different mock
// shape for cron.list, cron.runs, and agents.list.
const state = vi.hoisted(() => {
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
    sampleJob,
    sampleRun,
    cronListReturn: {
      data: { jobs: [sampleJob] } as { jobs: unknown[] } | undefined,
      error: null as Error | null,
    },
    cronRunsReturn: {
      data: { entries: [sampleRun] } as { entries: unknown[] } | undefined,
      error: null as Error | null,
    },
    agentsReturn: {
      data: { agents: [{ id: "a-1", name: "Agent" }] } as
        | { agents: unknown[] }
        | undefined,
    },
    mutateCronList: vi.fn(),
    mutateCronRuns: vi.fn(),
    rpcMutationFn: vi.fn().mockResolvedValue({}),
  };
});

vi.mock("@/hooks/useGatewayRpc", () => {
  return {
    useGatewayRpc: (method: string | null) => {
      if (method === "cron.list") {
        return {
          data: state.cronListReturn.data,
          error: state.cronListReturn.error,
          isLoading: false,
          mutate: state.mutateCronList,
        };
      }
      if (method === "cron.runs") {
        return {
          data: state.cronRunsReturn.data,
          error: state.cronRunsReturn.error,
          isLoading: false,
          mutate: state.mutateCronRuns,
        };
      }
      if (method === "agents.list") {
        return {
          data: state.agentsReturn.data,
          error: null,
          isLoading: false,
          mutate: vi.fn(),
        };
      }
      if (method === "chat.history") {
        return { data: undefined, error: null, isLoading: false, mutate: vi.fn() };
      }
      return { data: null, error: null, isLoading: false, mutate: vi.fn() };
    },
    useGatewayRpcMutation: () => state.rpcMutationFn,
  };
});

vi.mock("@/hooks/useAgents", () => ({
  useAgents: () => ({
    data: state.agentsReturn.data,
    error: null,
    isLoading: false,
    mutate: vi.fn(),
  }),
}));

function resetState() {
  state.cronListReturn.data = { jobs: [state.sampleJob] };
  state.cronListReturn.error = null;
  state.cronRunsReturn.data = { entries: [state.sampleRun] };
  state.cronRunsReturn.error = null;
  state.agentsReturn.data = { agents: [{ id: "a-1", name: "Agent" }] };
  state.mutateCronList.mockReset();
  state.mutateCronRuns.mockReset();
  state.rpcMutationFn.mockReset();
  state.rpcMutationFn.mockResolvedValue({});
}

describe("CronPanel ViewState", () => {
  beforeEach(() => {
    resetState();
  });

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

describe("CronPanel edge cases", () => {
  beforeEach(() => {
    resetState();
  });

  it("disables 'New cron' and shows helper text when no agents exist", () => {
    state.agentsReturn.data = { agents: [] };
    render(<CronPanel />);
    const createBtn = screen.getByRole("button", { name: /new cron/i });
    expect(createBtn).toBeDisabled();
    expect(screen.getByText(/create an agent first/i)).toBeInTheDocument();
  });

  it("shows an error banner with retry when cron.list revalidation fails", () => {
    state.cronListReturn.error = new Error("network down");
    render(<CronPanel />);
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(/network down/i);
    const retry = screen.getByRole("button", { name: /retry/i });
    fireEvent.click(retry);
    expect(state.mutateCronList).toHaveBeenCalled();
  });

  it("shows an error banner with retry when cron.runs fails in State B", () => {
    // Keep stale run entries so the user can still enter State B even while
    // cron.runs errors on the next revalidation.
    state.cronRunsReturn.error = new Error("runs failed");
    state.cronRunsReturn.data = { entries: [state.sampleRun] };
    render(<CronPanel />);
    fireEvent.click(screen.getByText("Daily digest"));
    fireEvent.click(screen.getByText("Sample run output"));
    // We should now be in State B with the error banner rendered in the left
    // column above the RunList.
    expect(screen.getByRole("button", { name: /back to jobs/i })).toBeInTheDocument();
    const alerts = screen.getAllByRole("alert");
    const runsAlert = alerts.find((a) => /failed to load runs/i.test(a.textContent ?? ""));
    expect(runsAlert).toBeDefined();
    // Retry button inside the banner triggers mutate.
    const retry = within(runsAlert as HTMLElement).getByRole("button", { name: /retry/i });
    fireEvent.click(retry);
    expect(state.mutateCronRuns).toHaveBeenCalled();
  });

  it("shows (deleted) badge and disables Run now/Edit job when the job was deleted", () => {
    // Render RunDetailPanel directly with an undefined job to cover the
    // deleted-in-flight case end-to-end.
    render(
      <RunDetailPanel
        run={state.sampleRun as never}
        job={undefined}
        onClose={() => {}}
        onRunNow={() => {}}
        onEdit={() => {}}
      />,
    );
    // The (deleted) badge is rendered in the header.
    expect(screen.getByText(/\(deleted\)/i)).toBeInTheDocument();
    // Run now / Edit job are disabled.
    expect(screen.getByRole("button", { name: /run now/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /edit job/i })).toBeDisabled();
  });

  it("flips the enabled badge optimistically when toggling pause/resume", async () => {
    // Make the RPC hang so we can observe the optimistic state before
    // resolution.
    let resolveRpc: (value: unknown) => void = () => {};
    state.rpcMutationFn.mockImplementation(
      () => new Promise((resolve) => {
        resolveRpc = resolve;
      }),
    );
    render(<CronPanel />);
    // The job starts enabled -- badge reads "active".
    expect(screen.getByText(/active/i)).toBeInTheDocument();
    // Expand the job card to reveal controls.
    fireEvent.click(screen.getByText("Daily digest"));
    // Click the Disable button (job is currently enabled).
    const disableBtn = screen.getByRole("button", { name: /^disable$/i });
    fireEvent.click(disableBtn);
    // The RPC was fired but hasn't resolved. Despite that, the optimistic
    // override should have flipped the badge to "paused" immediately.
    expect(state.rpcMutationFn).toHaveBeenCalledWith(
      "cron.update",
      expect.objectContaining({
        id: "job-1",
        patch: expect.objectContaining({ enabled: false }),
      }),
    );
    expect(screen.getByText(/paused/i)).toBeInTheDocument();
    await act(async () => {
      resolveRpc({});
    });
  });
});
