"use client";

import { useTeamsApi } from "@/hooks/useTeamsApi";

interface ActivityEvent {
  id: string;
  type: string;
  actor?: string;
  target?: string;
  createdAt?: string;
  description?: string;
}

export function ActivityPanel() {
  const { read } = useTeamsApi();
  const { data, isLoading, error } = read<{ events: ActivityEvent[] }>(
    "/activity",
  );

  if (isLoading) return <div className="p-8">Loading…</div>;
  if (error) return <div className="p-8 text-red-600">Error: {String(error)}</div>;

  return (
    <div className="p-8 max-w-4xl">
      <h1 className="text-2xl font-semibold mb-6">Activity</h1>
      <ul className="divide-y border rounded">
        {(data?.events ?? []).map((e) => (
          <li key={e.id} className="p-4 flex justify-between items-start gap-4">
            <div>
              <div className="text-xs text-zinc-500">{e.type}</div>
              <div className="text-sm">
                {e.description ?? `${e.actor ?? "?"} → ${e.target ?? "?"}`}
              </div>
            </div>
            {e.createdAt && (
              <div className="text-xs text-zinc-400 whitespace-nowrap">
                {e.createdAt}
              </div>
            )}
          </li>
        ))}
        {(data?.events ?? []).length === 0 && (
          <li className="p-4 text-sm text-zinc-500">No activity yet.</li>
        )}
      </ul>
    </div>
  );
}
