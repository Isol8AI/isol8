import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { JobList } from "@/components/control/panels/cron/JobList";
import type { CronJob } from "@/components/control/panels/cron/types";

const makeJob = (id: string, name: string): CronJob => ({
  id,
  name,
  enabled: true,
  createdAtMs: 1_700_000_000_000,
  updatedAtMs: 1_700_000_000_000,
  schedule: { kind: "cron", expr: "0 7 * * *", tz: "UTC" },
  sessionTarget: "isolated",
  wakeMode: "next-heartbeat",
  payload: { kind: "agentTurn", message: "do something" },
  state: {},
});

const cardHandlers = {
  expandedJobId: null as string | null,
  onToggleExpand: vi.fn(),
  onCreate: vi.fn(),
  onEdit: vi.fn(),
  onPauseResume: vi.fn(),
  onRunNow: vi.fn(),
  onDelete: vi.fn(),
  onSelectRun: vi.fn(),
};

describe("JobList", () => {
  it("renders empty state when no jobs", () => {
    render(<JobList jobs={[]} {...cardHandlers} />);
    expect(screen.getByText(/no crons yet/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /create your first cron/i }),
    ).toBeInTheDocument();
  });

  it("renders N job cards when jobs exist", () => {
    const jobs = [makeJob("1", "a"), makeJob("2", "b"), makeJob("3", "c")];
    render(<JobList jobs={jobs} {...cardHandlers} />);
    expect(screen.getAllByRole("article")).toHaveLength(3);
  });

  it("shows + New cron button when jobs exist", () => {
    render(<JobList jobs={[makeJob("1", "a")]} {...cardHandlers} />);
    expect(screen.getByRole("button", { name: /new cron/i })).toBeInTheDocument();
  });
});
