"use client";

import { useTeamsApi } from "@/hooks/useTeamsApi";

interface Skill {
  id: string;
  name: string;
  description?: string;
  version?: string;
}

export function SkillsPanel() {
  const { read } = useTeamsApi();
  const { data, isLoading, error } = read<{ skills: Skill[] }>("/skills");

  if (isLoading) return <div className="p-8">Loading…</div>;
  if (error) return <div className="p-8 text-red-600">Error: {String(error)}</div>;

  return (
    <div className="p-8 max-w-4xl">
      <h1 className="text-2xl font-semibold mb-2">Skills</h1>
      <p className="text-xs text-zinc-500 mb-6">
        Skills are operator-curated. To add or modify, contact your administrator.
      </p>
      <ul className="divide-y border rounded">
        {(data?.skills ?? []).map((s) => (
          <li key={s.id} className="p-4">
            <div className="flex justify-between">
              <div className="font-medium">{s.name}</div>
              {s.version && (
                <div className="text-xs text-zinc-500 font-mono">
                  v{s.version}
                </div>
              )}
            </div>
            {s.description && (
              <div className="text-xs text-zinc-500 mt-1">{s.description}</div>
            )}
          </li>
        ))}
        {(data?.skills ?? []).length === 0 && (
          <li className="p-4 text-sm text-zinc-500">No skills available.</li>
        )}
      </ul>
    </div>
  );
}
