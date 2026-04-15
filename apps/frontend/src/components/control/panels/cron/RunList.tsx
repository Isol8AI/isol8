"use client";
import { RunListRow } from "./RunListRow";
import { RunFilters, type RunStatusFilter } from "./RunFilters";
import type { CronRunEntry } from "./types";

interface RunListProps {
  runs: CronRunEntry[];
  selectedTs: number | null;
  onSelect: (run: CronRunEntry) => void;
  statusFilter: RunStatusFilter;
  queryFilter: string;
  onStatusFilterChange: (s: RunStatusFilter) => void;
  onQueryFilterChange: (q: string) => void;
  hasMore: boolean;
  onLoadMore: () => void;
  isLoading: boolean;
}

export function RunList(props: RunListProps) {
  return (
    <div className="flex flex-col h-full">
      <RunFilters
        status={props.statusFilter}
        query={props.queryFilter}
        onStatusChange={props.onStatusFilterChange}
        onQueryChange={props.onQueryFilterChange}
      />
      <div role="rowgroup" className="flex-1 overflow-y-auto">
        {props.runs.map((run) => (
          <RunListRow
            key={run.triggeredAtMs}
            run={run}
            selected={props.selectedTs === run.triggeredAtMs}
            onSelect={() => props.onSelect(run)}
          />
        ))}
        {props.hasMore && (
          <button
            onClick={props.onLoadMore}
            disabled={props.isLoading}
            className="w-full text-center py-3 text-sm text-[#8a8578] hover:text-[#1a1a1a]"
          >
            {props.isLoading ? "Loading…" : "Load more"}
          </button>
        )}
      </div>
    </div>
  );
}
