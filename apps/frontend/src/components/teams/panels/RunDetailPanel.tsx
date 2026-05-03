"use client";

import { useTeamsApi } from "@/hooks/useTeamsApi";

interface Run {
  id: string;
  status: string;
  transcript?: string;
}

export function RunDetailPanel({ runId }: { runId: string }) {
  const { read } = useTeamsApi();
  const { data, isLoading } = read<Run>(`/runs/${runId}`);

  if (isLoading) return <div className="p-8">Loading…</div>;

  return (
    <div className="p-8 max-w-4xl">
      <h1 className="text-xl font-semibold mb-4">Run {data?.id}</h1>
      <div className="text-sm text-zinc-500 mb-4">
        Status: {data?.status}
      </div>
      <pre className="bg-zinc-50 border rounded p-4 text-xs whitespace-pre-wrap">
        {data?.transcript ?? "(no transcript)"}
      </pre>
    </div>
  );
}
