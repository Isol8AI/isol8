import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { RunList } from "@/components/control/panels/cron/RunList";
import type { CronRunEntry } from "@/components/control/panels/cron/types";

const makeRun = (triggeredAtMs: number, overrides: Partial<CronRunEntry> = {}): CronRunEntry => ({
  jobId: "job-1",
  triggeredAtMs,
  status: "ok",
  durationMs: 1500,
  summary: `run at ${triggeredAtMs}`,
  ...overrides,
});

const baseProps = {
  statusFilter: "all" as const,
  queryFilter: "",
  onStatusFilterChange: vi.fn(),
  onQueryFilterChange: vi.fn(),
  hasMore: false,
  onLoadMore: vi.fn(),
  isLoading: false,
};

describe("RunList", () => {
  it("renders a row per run and marks the selected one aria-selected=true", () => {
    const runs = [
      makeRun(1_700_000_100_000),
      makeRun(1_700_000_200_000),
      makeRun(1_700_000_300_000),
    ];
    render(
      <RunList
        {...baseProps}
        runs={runs}
        selectedTs={1_700_000_200_000}
        onSelect={vi.fn()}
      />,
    );
    const rows = screen.getAllByRole("row");
    expect(rows).toHaveLength(3);
    expect(rows[0].getAttribute("aria-selected")).toBe("false");
    expect(rows[1].getAttribute("aria-selected")).toBe("true");
    expect(rows[2].getAttribute("aria-selected")).toBe("false");
  });

  it("invokes onSelect with the run when an unselected row is clicked", () => {
    const runs = [
      makeRun(1_700_000_100_000),
      makeRun(1_700_000_200_000),
      makeRun(1_700_000_300_000),
    ];
    const onSelect = vi.fn();
    render(
      <RunList
        {...baseProps}
        runs={runs}
        selectedTs={1_700_000_200_000}
        onSelect={onSelect}
      />,
    );
    const rows = screen.getAllByRole("row");
    fireEvent.click(rows[2]);
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith(runs[2]);
  });

  it("renders a Load more button when hasMore is true and invokes onLoadMore", () => {
    const onLoadMore = vi.fn();
    render(
      <RunList
        {...baseProps}
        runs={[makeRun(1_700_000_100_000)]}
        selectedTs={null}
        onSelect={vi.fn()}
        hasMore={true}
        onLoadMore={onLoadMore}
      />,
    );
    const loadMore = screen.getByRole("button", { name: /load more/i });
    fireEvent.click(loadMore);
    expect(onLoadMore).toHaveBeenCalledTimes(1);
  });
});
