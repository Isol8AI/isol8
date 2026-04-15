"use client";

import { useState } from "react";
import {
  Loader2,
  Clock,
  Play,
  Pencil,
  Trash2,
  ChevronDown,
  ChevronRight,
  CheckCircle2,
  XCircle,
  MinusCircle,
} from "lucide-react";
import { useGatewayRpc } from "@/hooks/useGatewayRpc";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { formatSchedule, formatDuration, formatAbsoluteTime, formatDelivery } from "./formatters";
import type { CronJob, CronRunEntry, CronRunStatus, CronRunsResponse } from "./types";

// --- Status badge ---

function StatusBadge({ status }: { status?: CronRunStatus }) {
  if (!status) return null;
  const config = {
    ok: { icon: CheckCircle2, label: "OK", className: "text-[#2d8a4e]" },
    error: { icon: XCircle, label: "Error", className: "text-red-500" },
    skipped: { icon: MinusCircle, label: "Skipped", className: "text-yellow-500" },
  };
  const { icon: Icon, label, className } = config[status];
  return (
    <span className={cn("inline-flex items-center gap-1 text-xs", className)}>
      <Icon className="h-3 w-3" />
      {label}
    </span>
  );
}

// --- Run history ---

function RunHistory({ jobId }: { jobId: string }) {
  const { data, error, isLoading } = useGatewayRpc<CronRunsResponse>("cron.runs", {
    scope: "job",
    id: jobId,
    limit: 10,
    sortDir: "desc",
  });

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 py-2 text-xs text-[#8a8578]">
        <Loader2 className="h-3 w-3 animate-spin" /> Loading history...
      </div>
    );
  }

  if (error) {
    return <p className="text-xs text-destructive py-1">Failed to load history</p>;
  }

  const entries = data?.entries ?? [];
  if (entries.length === 0) {
    return <p className="text-xs text-[#8a8578] py-1">No runs yet</p>;
  }

  return (
    <div className="space-y-1">
      {entries.map((entry) => (
        <div key={entry.triggeredAtMs} className="flex items-center gap-3 text-xs py-1 border-t border-[#e0dbd0]">
          <StatusBadge status={entry.status} />
          <span className="text-[#8a8578]">{formatAbsoluteTime(entry.triggeredAtMs)}</span>
          {entry.durationMs != null && (
            <span className="text-[#8a8578]">{formatDuration(entry.durationMs)}</span>
          )}
          {entry.summary && (
            <span className="text-[#5a5549] truncate flex-1">{entry.summary}</span>
          )}
          {entry.error && (
            <span className="text-destructive truncate flex-1">{entry.error}</span>
          )}
        </div>
      ))}
    </div>
  );
}

// --- JobCard ---

export interface JobCardProps {
  job: CronJob;
  expanded: boolean;
  onToggleExpand: () => void;
  onEdit: () => void;
  onPauseResume: () => void;
  onRunNow: () => void;
  onDelete: () => void;
  onSelectRun: (run: CronRunEntry) => void;
}

export function JobCard({
  job,
  expanded,
  onToggleExpand,
  onEdit,
  onPauseResume,
  onRunNow,
  onDelete,
  onSelectRun: _onSelectRun, // TODO(Task 7): wire run row onClick
}: JobCardProps) {
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  const consecutiveErrors = job.state?.consecutiveErrors ?? 0;
  const showErrorBadge =
    job.enabled && consecutiveErrors >= 1 && job.state?.lastRunStatus === "error";
  const isRunning = Boolean(job.state?.runningAtMs);

  return (
    <div
      role="article"
      className={cn(
        "rounded-lg border border-[#e0dbd0] overflow-hidden",
        isRunning && "ring-2 ring-blue-400 ring-offset-2 animate-pulse",
      )}
    >
      {/* Job header */}
      <div className="p-3 space-y-2">
        <div className="flex items-center justify-between">
          <button
            className="flex items-center gap-2 text-left flex-1 min-w-0"
            onClick={onToggleExpand}
          >
            {expanded ? (
              <ChevronDown className="h-3.5 w-3.5 opacity-50 shrink-0" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5 opacity-50 shrink-0" />
            )}
            <Clock className="h-3.5 w-3.5 opacity-50 shrink-0" />
            <span className="text-sm font-medium truncate">{job.name || job.id}</span>
            <span
              className={cn(
                "text-[10px] px-1.5 py-0.5 rounded-full shrink-0",
                job.enabled
                  ? "bg-[#e8f5e9] text-[#2d8a4e]"
                  : "bg-[#f3efe6] text-[#8a8578]",
              )}
            >
              {job.enabled ? "active" : "paused"}
            </span>
            {showErrorBadge && (
              <span className="text-xs px-2 py-0.5 rounded bg-red-100 text-red-800 shrink-0">
                {consecutiveErrors} consecutive errors
              </span>
            )}
          </button>
          <div className="flex gap-1 shrink-0">
            <Button
              variant="ghost"
              size="sm"
              onClick={onRunNow}
              title="Run now"
            >
              <Play className="h-3.5 w-3.5" />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={onEdit}
              title="Edit"
            >
              <Pencil className="h-3.5 w-3.5" />
            </Button>
            <Button
              variant={job.enabled ? "outline" : "default"}
              size="sm"
              onClick={onPauseResume}
            >
              {job.enabled ? "Disable" : "Enable"}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setConfirmingDelete((v) => !v)}
              title="Delete"
              className="text-destructive/70 hover:text-destructive"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>

        {/* Prompt preview */}
        <div className="pl-7">
          {(() => {
            if (job.payload.kind === "agentTurn") {
              const msg = job.payload.message;
              const truncated = msg.length > 200 ? msg.slice(0, 200) + "…" : msg;
              return (
                <p className="text-sm text-[#5a5549] line-clamp-2" title={msg}>
                  {truncated}
                </p>
              );
            }
            // systemEvent
            const text = job.payload.text;
            const truncated = text.length > 200 ? text.slice(0, 200) + "…" : text;
            return (
              <p className="text-sm text-[#5a5549] line-clamp-2" title={text}>
                <span className="text-xs uppercase tracking-wide text-[#8a8578] mr-2">
                  system event
                </span>
                {truncated}
              </p>
            );
          })()}
          {job.description && (
            <p className="text-xs text-[#8a8578] mt-1">{job.description}</p>
          )}
        </div>

        {/* Schedule + last run info + delivery */}
        <div className="flex items-center gap-3 text-xs text-[#8a8578] pl-7 flex-wrap">
          <span>{formatSchedule(job.schedule)}</span>
          {job.state?.lastRunStatus && (
            <>
              <span>&middot;</span>
              <StatusBadge status={job.state.lastRunStatus} />
            </>
          )}
          {job.state?.nextRunAtMs && (
            <>
              <span>&middot;</span>
              <span>Next: {formatAbsoluteTime(job.state.nextRunAtMs)}</span>
            </>
          )}
          {isRunning && (
            <>
              <span>&middot;</span>
              <span className="inline-flex items-center gap-2 text-xs text-blue-600">
                <span className="h-2 w-2 rounded-full bg-blue-500 animate-pulse" />
                Running now…
              </span>
            </>
          )}
          <span>&middot;</span>
          <span>Delivers to: {formatDelivery(job.delivery)}</span>
        </div>
      </div>

      {/* Delete confirmation */}
      {confirmingDelete && (
        <div className="px-3 pb-3">
          <div className="flex items-center justify-between rounded-md bg-destructive/10 border border-destructive/20 px-3 py-2">
            <span className="text-sm text-destructive">
              Delete &ldquo;{job.name || job.id}&rdquo;? This cannot be undone.
            </span>
            <div className="flex gap-1">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setConfirmingDelete(false)}
              >
                Cancel
              </Button>
              <Button
                variant="destructive"
                size="sm"
                onClick={() => {
                  setConfirmingDelete(false);
                  onDelete();
                }}
              >
                Delete
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Expanded: run history */}
      {expanded && (
        <div className="px-3 pb-3 pl-7 border-t border-[#e0dbd0]">
          <p className="text-xs font-medium text-[#8a8578] pt-2 pb-1">Run History</p>
          <RunHistory jobId={job.id} />
        </div>
      )}
    </div>
  );
}
