// apps/frontend/src/components/teams/shared/components/StatusIcon.tsx

// Ported from upstream Paperclip's StatusIcon.tsx
// (paperclip/ui/src/components/StatusIcon.tsx) (MIT, (c) 2025 Paperclip AI).
// See spec at docs/superpowers/specs/2026-05-04-teams-inbox-deep-port-design.md

import { useState } from "react";
import { cn } from "@/lib/utils";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Button } from "@/components/ui/button";
import type {
  IssueBlockerAttention,
  IssueBlockerAttentionReason,
  IssueBlockerAttentionState,
} from "@/components/teams/shared/types";

// Re-export the rich `IssueBlockerAttention` shape (hoisted to types.ts so
// the slim `Issue.blockerAttention` field can carry it). Existing imports
// from `./StatusIcon` continue to work.
export type {
  IssueBlockerAttention,
  IssueBlockerAttentionReason,
  IssueBlockerAttentionState,
};

// Inlined copy of the upstream `issueStatusIcon` map from
// `paperclip/ui/src/lib/status-colors.ts` with the retheme mapping applied:
//   `text-blue-{600,400}` for `todo`  ->  `text-amber-700 dark:text-amber-400`
// All other status hues are status-semantic and pass through unchanged
// (yellow / violet / green / red / neutral / muted-foreground).
const issueStatusIcon: Record<string, string> = {
  backlog: "text-muted-foreground border-muted-foreground",
  todo: "text-amber-700 dark:text-amber-400 border-amber-700 dark:border-amber-400",
  in_progress:
    "text-yellow-600 border-yellow-600 dark:text-yellow-400 dark:border-yellow-400",
  in_review:
    "text-violet-600 border-violet-600 dark:text-violet-400 dark:border-violet-400",
  done: "text-green-600 border-green-600 dark:text-green-400 dark:border-green-400",
  cancelled: "text-neutral-500 border-neutral-500",
  blocked: "text-red-600 border-red-600 dark:text-red-400 dark:border-red-400",
};

const issueStatusIconDefault = "text-muted-foreground border-muted-foreground";

const allStatuses = [
  "backlog",
  "todo",
  "in_progress",
  "in_review",
  "done",
  "cancelled",
  "blocked",
];

function statusLabel(status: string): string {
  return status.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

interface StatusIconProps {
  status: string;
  blockerAttention?: IssueBlockerAttention | null;
  onChange?: (status: string) => void;
  className?: string;
  showLabel?: boolean;
}

function blockedAttentionLabel(
  blockerAttention: IssueBlockerAttention | null | undefined,
) {
  if (!blockerAttention || blockerAttention.state === "none") return "Blocked";

  if (blockerAttention.reason === "active_child") {
    const count = blockerAttention.coveredBlockerCount;
    if (count === 1 && blockerAttention.sampleBlockerIdentifier) {
      return `Blocked · waiting on active sub-issue ${blockerAttention.sampleBlockerIdentifier}`;
    }
    if (count === 1) return "Blocked · waiting on 1 active sub-issue";
    return `Blocked · waiting on ${count} active sub-issues`;
  }

  if (blockerAttention.reason === "active_dependency") {
    const count = blockerAttention.coveredBlockerCount;
    if (count === 1 && blockerAttention.sampleBlockerIdentifier) {
      return `Blocked · covered by active dependency ${blockerAttention.sampleBlockerIdentifier}`;
    }
    if (count === 1) return "Blocked · covered by 1 active dependency";
    return `Blocked · covered by ${count} active dependencies`;
  }

  if (blockerAttention.reason === "stalled_review") {
    const count = blockerAttention.stalledBlockerCount;
    const leaf =
      blockerAttention.sampleStalledBlockerIdentifier ??
      blockerAttention.sampleBlockerIdentifier;
    if (count === 1 && leaf) return `Blocked · review stalled on ${leaf}`;
    if (count === 1) return "Blocked · review stalled with no clear next step";
    return `Blocked · ${count} reviews stalled with no clear next step`;
  }

  if (blockerAttention.reason === "attention_required") {
    const count = blockerAttention.unresolvedBlockerCount;
    return `Blocked · ${count} unresolved ${count === 1 ? "blocker needs" : "blockers need"} attention`;
  }

  return "Blocked";
}

export function StatusIcon({
  status,
  blockerAttention,
  onChange,
  className,
  showLabel,
}: StatusIconProps) {
  const [open, setOpen] = useState(false);
  const isCoveredBlocked =
    status === "blocked" && blockerAttention?.state === "covered";
  const isStalledBlocked =
    status === "blocked" && blockerAttention?.state === "stalled";
  const colorClass = isCoveredBlocked
    ? "text-cyan-600 border-cyan-600 dark:text-cyan-400 dark:border-cyan-400"
    : isStalledBlocked
      ? "text-amber-600 border-amber-600 dark:text-amber-400 dark:border-amber-400"
      : (issueStatusIcon[status] ?? issueStatusIconDefault);
  const isDone = status === "done";
  const ariaLabel =
    status === "blocked" ? blockedAttentionLabel(blockerAttention) : statusLabel(status);
  const blockerAttentionState = isCoveredBlocked
    ? "covered"
    : isStalledBlocked
      ? "stalled"
      : undefined;

  const circle = (
    <span
      className={cn(
        "relative inline-flex h-4 w-4 rounded-full border-2 shrink-0",
        colorClass,
        onChange && !showLabel && "cursor-pointer",
        className,
      )}
      data-blocker-attention-state={blockerAttentionState}
      aria-label={ariaLabel}
      title={ariaLabel}
    >
      {isDone && (
        <span className="absolute inset-0 m-auto h-2 w-2 rounded-full bg-current" />
      )}
      {isCoveredBlocked && (
        <span className="absolute -bottom-0.5 -right-0.5 h-2 w-2 rounded-full border border-background bg-current" />
      )}
      {isStalledBlocked && (
        <span className="absolute inset-0 m-auto h-1.5 w-1.5 rounded-full bg-current" />
      )}
    </span>
  );

  if (!onChange)
    return showLabel ? (
      <span className="inline-flex items-center gap-1.5">
        {circle}
        <span className="text-sm">{statusLabel(status)}</span>
      </span>
    ) : (
      circle
    );

  const trigger = showLabel ? (
    <button className="inline-flex items-center gap-1.5 cursor-pointer hover:bg-accent/50 rounded px-1 -mx-1 py-0.5 transition-colors">
      {circle}
      <span className="text-sm">{statusLabel(status)}</span>
    </button>
  ) : (
    circle
  );

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>{trigger}</PopoverTrigger>
      <PopoverContent className="w-40 p-1" align="start">
        {allStatuses.map((s) => (
          <Button
            key={s}
            variant="ghost"
            size="sm"
            className={cn(
              "w-full justify-start gap-2 text-xs",
              s === status && "bg-accent",
            )}
            onClick={() => {
              onChange(s);
              setOpen(false);
            }}
          >
            <StatusIcon status={s} />
            {statusLabel(s)}
          </Button>
        ))}
      </PopoverContent>
    </Popover>
  );
}
