"use client";

import { useTeamsApi } from "@/hooks/useTeamsApi";

interface InboxItem {
  id: string;
  type: string;
  title: string;
  createdAt?: string;
  agentId?: string;
}

export function InboxPanel() {
  const { read, post } = useTeamsApi();
  const { data, mutate } = read<{ items: InboxItem[] }>("/inbox");

  async function dismiss(id: string) {
    await post(`/inbox/${id}/dismiss`, {});
    mutate();
  }

  return (
    <div className="p-8 max-w-4xl">
      <h1 className="text-2xl font-semibold mb-6">Inbox</h1>
      <ul className="divide-y border rounded">
        {(data?.items ?? []).map((it) => (
          <li
            key={it.id}
            className="p-4 flex justify-between items-center"
          >
            <div>
              <div className="text-xs text-zinc-500">{it.type}</div>
              <div>{it.title}</div>
            </div>
            <button
              onClick={() => dismiss(it.id)}
              className="text-sm text-zinc-500 hover:underline"
            >
              Dismiss
            </button>
          </li>
        ))}
        {(data?.items ?? []).length === 0 && (
          <li className="p-4 text-sm text-zinc-500">No new items.</li>
        )}
      </ul>
    </div>
  );
}
