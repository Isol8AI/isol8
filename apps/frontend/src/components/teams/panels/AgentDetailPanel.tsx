"use client";

import { useState } from "react";
import { useTeamsApi } from "@/hooks/useTeamsApi";

interface Agent {
  id: string;
  name: string;
  role: string;
}

interface RunRow {
  id: string;
  status: string;
  startedAt?: string;
}

export function AgentDetailPanel({ agentId }: { agentId: string }) {
  const { read } = useTeamsApi();
  const { data: agent } = read<Agent>(`/agents/${agentId}`);
  const { data: runs } = read<{ runs: RunRow[] }>(`/agents/${agentId}/runs`);
  const [tab, setTab] = useState<"overview" | "runs" | "config">("overview");

  if (!agent) return <div className="p-8">Loading…</div>;

  return (
    <div className="p-8 max-w-4xl">
      <h1 className="text-2xl font-semibold mb-1">{agent.name}</h1>
      <div className="text-sm text-zinc-500 mb-6">{agent.role}</div>

      <div className="border-b mb-6">
        {(["overview", "runs", "config"] as const).map((t) => (
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
          {JSON.stringify(agent, null, 2)}
        </pre>
      )}
      {tab === "runs" && (
        <ul className="divide-y border rounded">
          {(runs?.runs ?? []).map((r) => (
            <li
              key={r.id}
              className="p-3 flex justify-between items-center"
            >
              <span>{r.status}</span>
              <a
                href={`/teams/agents/${agentId}/runs/${r.id}`}
                className="text-sm text-zinc-600 hover:underline"
              >
                Open →
              </a>
            </li>
          ))}
          {(runs?.runs ?? []).length === 0 && (
            <li className="p-3 text-sm text-zinc-500">No runs yet.</li>
          )}
        </ul>
      )}
      {tab === "config" && (
        <div className="text-sm text-zinc-500">
          Adapter configuration is managed by Isol8 and cannot be edited here.
        </div>
      )}
    </div>
  );
}
