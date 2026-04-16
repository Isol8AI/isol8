import { CheckCircle2, XCircle, MinusCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatRelativeTime, formatDuration } from "./formatters";
import type { CronRunEntry } from "./types";

const ICONS = {
  ok: <CheckCircle2 className="h-4 w-4 text-green-600" />,
  error: <XCircle className="h-4 w-4 text-red-600" />,
  skipped: <MinusCircle className="h-4 w-4 text-yellow-600" />,
};

export function RunListRow({
  run,
  selected,
  onSelect,
}: {
  run: CronRunEntry;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      role="row"
      aria-selected={selected}
      onClick={onSelect}
      className={cn(
        "w-full flex items-center gap-3 px-3 py-2 text-left hover:bg-[#f3efe6]",
        selected && "bg-[#e8e3d9]",
      )}
    >
      {ICONS[run.status]}
      <span className="text-sm">{formatRelativeTime(run.triggeredAtMs)}</span>
      {run.durationMs !== undefined && (
        <span className="text-xs text-[#8a8578] ml-auto">
          {formatDuration(run.durationMs)}
        </span>
      )}
      {run.delivered === false && run.deliveryStatus === "not-delivered" && (
        <span className="text-xs text-red-600" title={run.deliveryError}>
          ✗
        </span>
      )}
    </button>
  );
}
