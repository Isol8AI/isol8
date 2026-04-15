import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export type RunStatusFilter = "all" | "ok" | "error" | "skipped";

const STATUS_LABELS: Record<RunStatusFilter, string> = {
  all: "All",
  ok: "OK",
  error: "Error",
  skipped: "Skipped",
};

const STATUSES: RunStatusFilter[] = ["all", "ok", "error", "skipped"];

export function RunFilters({
  status,
  query,
  onStatusChange,
  onQueryChange,
}: {
  status: RunStatusFilter;
  query: string;
  onStatusChange: (s: RunStatusFilter) => void;
  onQueryChange: (q: string) => void;
}) {
  return (
    <div className="flex flex-col gap-2 p-2 border-b border-[#e0dbd0]">
      <div className="flex gap-1">
        {STATUSES.map((s) => (
          <Button
            key={s}
            variant={status === s ? "default" : "outline"}
            size="sm"
            onClick={() => onStatusChange(s)}
            className="text-xs"
          >
            {STATUS_LABELS[s]}
          </Button>
        ))}
      </div>
      <Input
        value={query}
        onChange={(e) => onQueryChange(e.target.value)}
        placeholder="Search summaries…"
        className="h-8 text-sm"
      />
    </div>
  );
}
