// apps/frontend/src/components/teams/issues/IssueProperties.tsx

// Ported from upstream Paperclip's pages/IssueDetail.tsx sidebar block
// (paperclip/ui/src/pages/IssueDetail.tsx) (MIT, (c) 2025 Paperclip AI).
// v1: read-only stack of label/value rows. Mutations live in IssueHeader.
// Drops assignee picker, labels editor, project picker, watcher list, etc.
// See spec at docs/superpowers/specs/2026-05-04-teams-inbox-deep-port-design.md

"use client";

import type { ReactNode } from "react";
import { StatusIcon } from "@/components/teams/shared/components/StatusIcon";
import { PriorityIcon } from "@/components/teams/shared/components/PriorityIcon";
import { timeAgo } from "@/components/teams/shared/lib/timeAgo";
import { cn } from "@/lib/utils";
import type {
  Issue,
  CompanyAgent,
  CompanyMember,
  IssueProject,
} from "@/components/teams/shared/types";

export interface IssuePropertiesProps {
  issue: Issue;
  agents?: CompanyAgent[];
  members?: CompanyMember[];
  projects?: IssueProject[];
  className?: string;
}

function PropertyRow({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="grid grid-cols-[100px_1fr] gap-3 items-baseline py-1.5 text-sm">
      <dt className="text-xs text-muted-foreground uppercase tracking-wide">
        {label}
      </dt>
      <dd className="min-w-0 truncate">{children}</dd>
    </div>
  );
}

export function IssueProperties({
  issue,
  agents = [],
  className,
}: IssuePropertiesProps) {
  const assigneeName = issue.assigneeAgentId
    ? (agents.find((a) => a.id === issue.assigneeAgentId)?.name ??
      "Unknown agent")
    : "Unassigned";

  // Project comes denormalized from the BFF as `issue.project`. The
  // `projects` / `members` props are accepted today so callers don't need to
  // refactor when v2 wires assignee/project pickers in.
  const project: IssueProject | null = issue.project ?? null;

  const labels = issue.labels ?? [];

  return (
    <dl className={cn("flex flex-col divide-y divide-border", className)}>
      <PropertyRow label="Status">
        <span className="inline-flex items-center gap-2">
          <StatusIcon status={issue.status} />
          <span className="capitalize">
            {issue.status.replace(/_/g, " ")}
          </span>
        </span>
      </PropertyRow>
      <PropertyRow label="Priority">
        {issue.priority ? (
          <span className="inline-flex items-center gap-2">
            <PriorityIcon priority={issue.priority} />
            <span className="capitalize">{issue.priority}</span>
          </span>
        ) : (
          <span className="text-muted-foreground">—</span>
        )}
      </PropertyRow>
      <PropertyRow label="Assignee">
        <span className={cn(!issue.assigneeAgentId && "text-muted-foreground")}>
          {assigneeName}
        </span>
      </PropertyRow>
      <PropertyRow label="Project">
        {project ? (
          <span>{project.name}</span>
        ) : (
          <span className="text-muted-foreground">—</span>
        )}
      </PropertyRow>
      <PropertyRow label="Labels">
        {labels.length > 0 ? (
          <span className="flex flex-wrap gap-1">
            {labels.map((l) => (
              <span
                key={l.id}
                className="rounded bg-accent/50 px-1.5 py-0.5 text-xs"
              >
                {l.name}
              </span>
            ))}
          </span>
        ) : (
          <span className="text-muted-foreground">—</span>
        )}
      </PropertyRow>
      <PropertyRow label="Created">
        {issue.createdAt ? (
          <time dateTime={issue.createdAt}>{timeAgo(issue.createdAt)}</time>
        ) : (
          <span className="text-muted-foreground">—</span>
        )}
      </PropertyRow>
      <PropertyRow label="Updated">
        {issue.updatedAt ? (
          <time dateTime={issue.updatedAt}>{timeAgo(issue.updatedAt)}</time>
        ) : (
          <span className="text-muted-foreground">—</span>
        )}
      </PropertyRow>
    </dl>
  );
}
