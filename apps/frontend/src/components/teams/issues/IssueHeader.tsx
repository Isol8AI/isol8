// apps/frontend/src/components/teams/issues/IssueHeader.tsx

// Ported from upstream Paperclip's pages/IssueDetail.tsx header section
// (paperclip/ui/src/pages/IssueDetail.tsx) (MIT, (c) 2025 Paperclip AI).
// v1: identifier + title (inline editable) + status + priority pickers.
// Drops assignee picker, parent issue, watcher list, run actions, plugin slots.
// See spec at docs/superpowers/specs/2026-05-04-teams-inbox-deep-port-design.md

"use client";

import { useState, useEffect, useRef } from "react";
import { StatusIcon } from "@/components/teams/shared/components/StatusIcon";
import { PriorityIcon } from "@/components/teams/shared/components/PriorityIcon";
import { cn } from "@/lib/utils";
import type {
  Issue,
  IssueStatus,
  IssuePriority,
} from "@/components/teams/shared/types";

export interface IssueHeaderProps {
  issue: Issue;
  /** Called when user saves a new title (blur or Enter). Async; component shows pending state. */
  onTitleSave: (title: string) => Promise<void>;
  onStatusChange: (status: IssueStatus) => Promise<void>;
  onPriorityChange: (priority: IssuePriority) => Promise<void>;
}

export function IssueHeader({
  issue,
  onTitleSave,
  onStatusChange,
  onPriorityChange,
}: IssueHeaderProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(issue.title);
  const [saving, setSaving] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // Sync draft when issue.title changes externally (e.g. mutation resolves
  // and the parent re-renders with the new title).
  useEffect(() => {
    setDraft(issue.title);
  }, [issue.title]);

  useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [editing]);

  const save = async () => {
    const trimmed = draft.trim();
    if (!trimmed || trimmed === issue.title) {
      setDraft(issue.title);
      setEditing(false);
      return;
    }
    setSaving(true);
    try {
      await onTitleSave(trimmed);
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };

  const cancel = () => {
    setDraft(issue.title);
    setEditing(false);
  };

  // PriorityIcon requires a non-null IssuePriority; fall back to "medium" so
  // the picker still renders for issues that have no priority set yet, letting
  // the user assign one via the popover.
  const renderedPriority: IssuePriority = issue.priority ?? "medium";

  return (
    <div className="flex flex-wrap items-center gap-3">
      {issue.identifier && (
        <span className="text-xs font-mono text-muted-foreground shrink-0">
          {issue.identifier}
        </span>
      )}

      {editing ? (
        <input
          ref={inputRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => void save()}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              void save();
            } else if (e.key === "Escape") {
              e.preventDefault();
              cancel();
            }
          }}
          className="flex-1 min-w-0 bg-transparent border-b border-border outline-none text-xl font-medium"
          disabled={saving}
        />
      ) : (
        <button
          type="button"
          onClick={() => setEditing(true)}
          className={cn(
            "flex-1 min-w-0 text-left text-xl font-medium hover:bg-accent/30 rounded px-1 -mx-1 transition-colors",
            saving && "opacity-50",
          )}
        >
          {issue.title}
        </button>
      )}

      <StatusIcon
        status={issue.status}
        blockerAttention={
          typeof issue.blockerAttention === "object"
            ? issue.blockerAttention
            : null
        }
        onChange={(s) => void onStatusChange(s as IssueStatus)}
        showLabel
      />

      <PriorityIcon
        priority={renderedPriority}
        onChange={(p) => void onPriorityChange(p)}
        showLabel
      />
    </div>
  );
}
