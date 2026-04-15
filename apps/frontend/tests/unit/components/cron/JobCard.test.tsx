import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { JobCard } from "@/components/control/panels/cron/JobCard";
import type { CronJob } from "@/components/control/panels/cron/types";

const baseJob: CronJob = {
  id: "job-1",
  name: "Daily digest",
  enabled: true,
  createdAtMs: 1_700_000_000_000,
  updatedAtMs: 1_700_000_000_000,
  schedule: { kind: "cron", expr: "0 7 * * *", tz: "UTC" },
  sessionTarget: "isolated",
  wakeMode: "next-heartbeat",
  payload: { kind: "agentTurn", message: "Summarize today's news" },
  state: {
    nextRunAtMs: Date.now() + 3600_000,
    lastRunStatus: "ok",
    lastRunAtMs: Date.now() - 120_000,
  },
};

const noopProps = {
  expanded: false,
  onToggleExpand: vi.fn(),
  onEdit: vi.fn(),
  onPauseResume: vi.fn(),
  onRunNow: vi.fn(),
  onDelete: vi.fn(),
  onSelectRun: vi.fn(),
};

describe("JobCard (refactor)", () => {
  it("renders name, formatted schedule, and active badge", () => {
    render(<JobCard job={baseJob} {...noopProps} />);
    expect(screen.getByText("Daily digest")).toBeInTheDocument();
    expect(screen.getByText(/active/i)).toBeInTheDocument();
    // formatSchedule for "0 7 * * *" renders via cronstrue; be permissive
    expect(screen.getByText(/7:00 AM|every day at 7/i)).toBeInTheDocument();
  });

  it("renders 'paused' badge when disabled", () => {
    render(<JobCard job={{ ...baseJob, enabled: false }} {...noopProps} />);
    expect(screen.getByText(/paused/i)).toBeInTheDocument();
  });
});
