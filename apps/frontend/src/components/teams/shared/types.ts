// apps/frontend/src/components/teams/shared/types.ts

// Ported from upstream Paperclip
// (https://github.com/Paperclip-AI/paperclip/tree/main/packages/shared/src/types)
// (MIT, © 2025 Paperclip AI). Subset retained for IssueRow / IssueColumns /
// IssueFiltersPopover. Full type lives in upstream packages/shared/src/types/.
// See spec at docs/superpowers/specs/2026-05-04-teams-inbox-deep-port-design.md

export type IssueStatus =
  | "todo"
  | "in_progress"
  | "in_review"
  | "pending"
  | "review"
  | "done"
  | "won_t_do"
  | "blocked"
  | "duplicate"
  | "open"
  | "closed";

export const ISSUE_STATUSES: readonly IssueStatus[] = [
  "todo",
  "in_progress",
  "in_review",
  "pending",
  "review",
  "done",
  "won_t_do",
  "blocked",
  "duplicate",
];

export type IssuePriority = "critical" | "high" | "medium" | "low";

export interface IssueLabel {
  id: string;
  name: string;
  color?: string | null;
}

export interface IssueProject {
  id: string;
  name: string;
  color?: string | null;
}

// Rich `blockerAttention` shape — hoisted from upstream Paperclip's StatusIcon
// so it can live alongside the slim `Issue` interface without creating an
// import cycle through the components/ subtree. Re-exported from
// `components/StatusIcon.tsx` for back-compat with existing call sites.
export type IssueBlockerAttentionState =
  | "none"
  | "covered"
  | "stalled"
  | "needs_attention";

export type IssueBlockerAttentionReason =
  | "active_child"
  | "active_dependency"
  | "stalled_review"
  | "attention_required"
  | null;

export interface IssueBlockerAttention {
  state: IssueBlockerAttentionState;
  reason: IssueBlockerAttentionReason;
  unresolvedBlockerCount: number;
  coveredBlockerCount: number;
  stalledBlockerCount: number;
  attentionBlockerCount: number;
  sampleBlockerIdentifier: string | null;
  sampleStalledBlockerIdentifier: string | null;
}

// Rich productivity-review payload — hoisted from upstream Paperclip's
// ProductivityReviewBadge so the `Issue.productivityReview` field can carry
// the full review metadata that StatusIcon / IssueRow consume. Re-exported
// from `components/ProductivityReviewBadge.tsx` for back-compat.
export type IssueProductivityReviewTrigger =
  | "no_comment_streak"
  | "long_active_duration"
  | "high_churn";

export interface IssueProductivityReview {
  reviewIssueId: string;
  reviewIdentifier: string | null;
  status: IssueStatus | string;
  trigger: IssueProductivityReviewTrigger | null;
  noCommentStreak: number | null;
}

export interface Issue {
  id: string;
  identifier?: string | null;
  title: string;
  status: IssueStatus;
  priority?: IssuePriority | null;
  labels?: IssueLabel[] | null;
  project?: IssueProject | null;
  parentId?: string | null;
  assigneeAgentId?: string | null;
  assigneeUserId?: string | null;
  createdByUserId?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
  lastActivityAt?: string | null;
  lastExternalCommentAt?: string | null;
  blockerAttention?: boolean | IssueBlockerAttention | null;
  productivityReview?: IssueProductivityReview | null;
  unread?: boolean | null;
  archivedAt?: string | null;
}

export interface Approval {
  id: string;
  issueId?: string | null;
  title?: string | null;
  status: "pending" | "approved" | "rejected";
  createdAt?: string | null;
  decidedAt?: string | null;
}

export interface HeartbeatRun {
  id: string;
  agentId?: string | null;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  startedAt?: string | null;
  completedAt?: string | null;
  failureReason?: string | null;
}

export interface CompanyMember {
  userId: string;
  name?: string | null;
  email?: string | null;
  imageUrl?: string | null;
}

export interface CompanyAgent {
  id: string;
  name: string;
  iconUrl?: string | null;
}
