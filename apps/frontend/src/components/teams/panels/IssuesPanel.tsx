"use client";

import { Loader2, CircleDot } from "lucide-react";
import Link from "next/link";
import { usePaperclipApi } from "@/hooks/usePaperclip";
import { cn } from "@/lib/utils";

interface Issue {
  id?: string;
  identifier?: string;
  title?: string;
  status?: string;
  assignee?: string;
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

export function IssuesPanel() {
  const { data, isLoading } = usePaperclipApi<Issue[]>("issues");

  const issues = Array.isArray(data) ? data : [];

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-[#8a8578]" />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-[#1a1a1a]">Issues</h1>
        <p className="text-sm text-[#8a8578]">{issues.length} issue{issues.length !== 1 ? "s" : ""}</p>
      </div>

      {issues.length === 0 ? (
        <div className="rounded-lg border border-[#e5e0d5] bg-white p-8 text-center">
          <CircleDot className="h-6 w-6 text-[#b0a99a] mx-auto mb-2" />
          <p className="text-sm text-[#8a8578]">No issues found</p>
        </div>
      ) : (
        <div className="rounded-lg border border-[#e5e0d5] bg-white divide-y divide-[#e5e0d5]">
          {issues.map((issue, idx) => (
            <Link key={issue.id ?? idx} href={`/teams/issues/${issue.id}`}>
              <div className="px-4 py-3 flex items-center gap-3 hover:bg-[#faf8f4] transition-colors cursor-pointer">
                <CircleDot className={cn("h-4 w-4 flex-shrink-0", statusColor(issue.status))} />
                {issue.identifier && (
                  <span className="text-xs text-[#b0a99a] font-mono flex-shrink-0">{issue.identifier}</span>
                )}
                <span className="flex-1 text-sm text-[#1a1a1a] truncate">{issue.title ?? "Untitled"}</span>
                {issue.assignee && (
                  <span className="text-xs text-[#8a8578] flex-shrink-0">{issue.assignee}</span>
                )}
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
