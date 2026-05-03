"use client";

import { useTeamsApi } from "@/hooks/useTeamsApi";

interface CostBreakdown {
  total_cents?: number;
  by_agent?: Array<{ agent_id: string; agent_name?: string; cents: number }>;
  by_project?: Array<{ project_id: string; project_name?: string; cents: number }>;
  period?: string;
}

function fmt(cents: number) {
  return `$${(cents / 100).toFixed(2)}`;
}

export function CostsPanel() {
  const { read } = useTeamsApi();
  const { data, isLoading, error } = read<CostBreakdown>("/costs");

  if (isLoading) return <div className="p-8">Loading…</div>;
  if (error) return <div className="p-8 text-red-600">Error: {String(error)}</div>;

  return (
    <div className="p-8 max-w-4xl">
      <h1 className="text-2xl font-semibold mb-1">Costs</h1>
      {data?.period && (
        <div className="text-sm text-zinc-500 mb-6">Period: {data.period}</div>
      )}

      <div className="border rounded p-4 mb-6 bg-white">
        <div className="text-xs text-zinc-500">Total</div>
        <div className="text-2xl font-semibold mt-1">
          {fmt(data?.total_cents ?? 0)}
        </div>
      </div>

      {data?.by_agent && data.by_agent.length > 0 && (
        <section className="mb-6">
          <h2 className="text-sm font-semibold mb-2">By agent</h2>
          <ul className="divide-y border rounded">
            {data.by_agent.map((row) => (
              <li
                key={row.agent_id}
                className="p-3 flex justify-between text-sm"
              >
                <span>{row.agent_name ?? row.agent_id}</span>
                <span className="font-mono">{fmt(row.cents)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {data?.by_project && data.by_project.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold mb-2">By project</h2>
          <ul className="divide-y border rounded">
            {data.by_project.map((row) => (
              <li
                key={row.project_id}
                className="p-3 flex justify-between text-sm"
              >
                <span>{row.project_name ?? row.project_id}</span>
                <span className="font-mono">{fmt(row.cents)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
