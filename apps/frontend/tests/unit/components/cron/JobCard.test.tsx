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

  it("shows truncated prompt preview from payload.message", () => {
    const longPrompt =
      "Summarize today's top 3 TechCrunch posts and email me a brief summary with links and author names and ".repeat(3);
    render(
      <JobCard
        job={{ ...baseJob, payload: { kind: "agentTurn", message: longPrompt } }}
        {...noopProps}
      />,
    );
    const el = screen.getByText(/Summarize today's top 3/);
    // 200 chars + ellipsis char (\u2026 = 1 char). Use 203 to be lenient with
    // whatever ellipsis string you pick, as long as it's short.
    expect(el.textContent!.length).toBeLessThanOrEqual(203);
    expect(el.textContent).toMatch(/…$/);
  });

  it("shows delivery summary from delivery.channel+to", () => {
    render(
      <JobCard
        job={{ ...baseJob, delivery: { mode: "announce", channel: "telegram", to: "@me" } }}
        {...noopProps}
      />,
    );
    expect(screen.getByText(/Delivers to:/i)).toBeInTheDocument();
    expect(screen.getByText(/Telegram @me/)).toBeInTheDocument();
  });

  it("shows running indicator when state.runningAtMs is set", () => {
    render(
      <JobCard
        job={{ ...baseJob, state: { ...baseJob.state, runningAtMs: Date.now() - 1000 } }}
        {...noopProps}
      />,
    );
    expect(screen.getByText(/Running now/i)).toBeInTheDocument();
  });

  it("shows description when set", () => {
    render(
      <JobCard
        job={{ ...baseJob, description: "Runs every morning at 7am" }}
        {...noopProps}
      />,
    );
    expect(screen.getByText("Runs every morning at 7am")).toBeInTheDocument();
  });

  it("shows consecutive errors badge when >= 1 and enabled", () => {
    render(
      <JobCard
        job={{
          ...baseJob,
          state: { ...baseJob.state, consecutiveErrors: 3, lastRunStatus: "error" },
        }}
        {...noopProps}
      />,
    );
    expect(screen.getByText(/3 consecutive errors/i)).toBeInTheDocument();
  });
});
