"use client";

import { Loader2, ArrowLeft, CircleDot } from "lucide-react";
import Link from "next/link";
import { usePaperclipApi } from "@/hooks/usePaperclip";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface Comment {
  id?: string;
  author?: string;
  body?: string;
  created_at?: string;
}

interface IssueDetail {
  id?: string;
  identifier?: string;
  title?: string;
  status?: string;
  priority?: string;
  assignee?: string;
  description?: string;
  comments?: Comment[];
}

function statusColor(status?: string) {
  switch (status) {
    case "done": return "text-[#2d8a4e]";
    case "in_progress": return "text-blue-500";
    case "todo": return "text-[#8a8578]";
    case "cancelled": return "text-[#b0a99a]";
    default: return "text-[#b0a99a]";
  }
}

function formatTime(ts?: string) {
  if (!ts) return "—";
  return new Date(ts).toLocaleDateString();
}

interface IssueDetailPanelProps {
  issueId: string;
}

export function IssueDetailPanel({ issueId }: IssueDetailPanelProps) {
  const { data: issue, isLoading } = usePaperclipApi<IssueDetail>(`issues/${issueId}`);

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-[#8a8578]" />
      </div>
    );
  }

  if (!issue) {
    return <div className="p-6 text-sm text-[#8a8578]">Issue not found.</div>;
  }

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center gap-2">
        <Link href="/teams/issues">
          <Button variant="ghost" size="sm">
            <ArrowLeft className="h-4 w-4 mr-1" />
            Back
          </Button>
        </Link>
      </div>

      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <CircleDot className={cn("h-4 w-4", statusColor(issue.status))} />
          {issue.identifier && (
            <span className="text-xs text-[#b0a99a] font-mono">{issue.identifier}</span>
          )}
        </div>
        <h1 className="text-lg font-semibold text-[#1a1a1a]">{issue.title ?? "Untitled"}</h1>
      </div>

      <div className="rounded-lg border border-[#e5e0d5] bg-white p-4 space-y-2">
        <Row label="Status" value={issue.status ?? "—"} />
        <Row label="Priority" value={issue.priority ?? "—"} />
        <Row label="Assignee" value={issue.assignee ?? "—"} />
      </div>

      {issue.description && (
        <div className="rounded-lg border border-[#e5e0d5] bg-white p-4">
          <h2 className="text-xs font-semibold text-[#8a8578] mb-2 uppercase tracking-wider">Description</h2>
          <p className="text-sm text-[#1a1a1a] whitespace-pre-wrap">{issue.description}</p>
        </div>
      )}

      {issue.comments && issue.comments.length > 0 && (
        <div className="space-y-2">
          <h2 className="text-sm font-semibold text-[#1a1a1a]">Comments</h2>
          <div className="space-y-2">
            {issue.comments.map((comment, idx) => (
              <div key={comment.id ?? idx} className="rounded-lg border border-[#e5e0d5] bg-white p-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-medium text-[#1a1a1a]">{comment.author ?? "Anonymous"}</span>
                  <span className="text-xs text-[#b0a99a]">{formatTime(comment.created_at)}</span>
                </div>
                <p className="text-sm text-[#1a1a1a]">{comment.body ?? ""}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-[#8a8578]">{label}</span>
      <span className="font-medium text-[#1a1a1a]">{value}</span>
    </div>
  );
}
