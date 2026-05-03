"use client";

import { useTeamsApi } from "@/hooks/useTeamsApi";

interface Issue {
  id: string;
  title: string;
  description?: string;
  status?: string;
  priority?: string;
  project_id?: string;
  assignee_agent_id?: string;
  created_at?: string;
}

export function IssueDetailPanel({ issueId }: { issueId: string }) {
  const { read } = useTeamsApi();
  const { data, isLoading } = read<Issue>(`/issues/${issueId}`);

  if (isLoading) return <div className="p-8">Loading…</div>;
  if (!data) return <div className="p-8 text-zinc-500">Issue not found.</div>;

  return (
    <div className="p-8 max-w-4xl">
      <h1 className="text-2xl font-semibold mb-2">{data.title}</h1>
      <div className="text-sm text-zinc-500 mb-6">
        {data.status ?? "open"}
        {data.priority ? ` · ${data.priority}` : ""}
      </div>
      {data.description && (
        <div className="mb-6 whitespace-pre-wrap text-sm">
          {data.description}
        </div>
      )}
      <pre className="bg-zinc-50 border rounded p-4 text-xs whitespace-pre-wrap">
        {JSON.stringify(data, null, 2)}
      </pre>
    </div>
  );
}
