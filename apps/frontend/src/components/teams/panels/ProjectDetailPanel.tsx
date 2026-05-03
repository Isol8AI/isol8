"use client";

import { useState } from "react";
import { useTeamsApi } from "@/hooks/useTeamsApi";

interface Project {
  id: string;
  name: string;
  description?: string;
  budget_monthly_cents?: number;
}

export function ProjectDetailPanel({ projectId }: { projectId: string }) {
  const { read } = useTeamsApi();
  const { data, isLoading } = read<Project>(`/projects/${projectId}`);
  const [tab, setTab] = useState<"overview" | "issues" | "budget">("overview");

  if (isLoading) return <div className="p-8">Loading…</div>;
  if (!data) return <div className="p-8 text-zinc-500">Project not found.</div>;

  return (
    <div className="p-8 max-w-4xl">
      <h1 className="text-2xl font-semibold mb-1">{data.name}</h1>
      {data.description && (
        <div className="text-sm text-zinc-500 mb-6">{data.description}</div>
      )}

      <div className="border-b mb-6">
        {(["overview", "issues", "budget"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm ${
              tab === t
                ? "border-b-2 border-zinc-900"
                : "text-zinc-500"
            }`}
          >
            {t[0].toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {tab === "overview" && (
        <pre className="text-xs bg-zinc-50 border rounded p-4 whitespace-pre-wrap">
          {JSON.stringify(data, null, 2)}
        </pre>
      )}
      {tab === "issues" && (
        <div className="text-sm text-zinc-500">
          Issues per project — coming soon.
        </div>
      )}
      {tab === "budget" && (
        <div className="text-sm text-zinc-500">
          Budget breakdown — coming soon.
        </div>
      )}
    </div>
  );
}
