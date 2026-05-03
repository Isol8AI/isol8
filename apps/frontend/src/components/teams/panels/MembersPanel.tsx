"use client";

import { useTeamsApi } from "@/hooks/useTeamsApi";

interface Member {
  id: string;
  user_id?: string;
  role?: string;
  email_via_clerk?: string;
  joined_at?: string;
}

export function MembersPanel() {
  const { read } = useTeamsApi();
  const { data, isLoading, error } = read<{ members: Member[] }>("/members");

  if (isLoading) return <div className="p-8">Loading…</div>;
  if (error) return <div className="p-8 text-red-600">Error: {String(error)}</div>;

  return (
    <div className="p-8 max-w-4xl">
      <h1 className="text-2xl font-semibold mb-6">Members</h1>
      <ul className="divide-y border rounded">
        {(data?.members ?? []).map((m) => (
          <li
            key={m.id}
            className="p-4 flex justify-between items-center"
          >
            <div>
              <div className="text-sm">
                {m.email_via_clerk ?? m.user_id ?? m.id}
              </div>
              {m.role && (
                <div className="text-xs text-zinc-500">{m.role}</div>
              )}
            </div>
            {m.joined_at && (
              <div className="text-xs text-zinc-400">{m.joined_at}</div>
            )}
          </li>
        ))}
        {(data?.members ?? []).length === 0 && (
          <li className="p-4 text-sm text-zinc-500">No members yet.</li>
        )}
      </ul>
    </div>
  );
}
