"use client";

import { useState } from "react";
import { useTeamsApi } from "@/hooks/useTeamsApi";

interface Agent {
  id: string;
  name: string;
  role: string;
  status?: string;
}

export function AgentsListPanel() {
  const { read } = useTeamsApi();
  const { data, isLoading, error, mutate } = read<{ agents: Agent[] }>("/agents");
  const [creating, setCreating] = useState(false);

  if (isLoading) return <div className="p-8">Loading…</div>;
  if (error) return <div className="p-8 text-red-600">Error: {String(error)}</div>;

  return (
    <div className="p-8 max-w-4xl">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-semibold">Agents</h1>
        <button
          onClick={() => setCreating(true)}
          className="px-4 py-2 bg-zinc-900 text-white rounded text-sm"
        >
          New agent
        </button>
      </div>

      <ul className="divide-y border rounded">
        {(data?.agents ?? []).map((a) => (
          <li
            key={a.id}
            className="flex justify-between items-center p-4"
          >
            <div>
              <div className="font-medium">{a.name}</div>
              <div className="text-xs text-zinc-500">{a.role}</div>
            </div>
            <a
              href={`/teams/agents/${a.id}`}
              className="text-sm text-zinc-600 hover:underline"
            >
              Open →
            </a>
          </li>
        ))}
        {(data?.agents ?? []).length === 0 && (
          <li className="p-4 text-sm text-zinc-500">No agents yet.</li>
        )}
      </ul>

      {creating && (
        <CreateAgentDialog
          onClose={() => setCreating(false)}
          onCreated={() => {
            setCreating(false);
            mutate();
          }}
        />
      )}
    </div>
  );
}

function CreateAgentDialog({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const { post } = useTeamsApi();
  const [name, setName] = useState("");
  const [role, setRole] = useState("engineer");
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit() {
    setSubmitting(true);
    setErr(null);
    try {
      // SECURITY: body intentionally contains NO adapterType, NO adapterConfig,
      // NO url, NO authToken. The BFF synthesizes the openclaw_gateway adapter
      // server-side via core.services.paperclip_adapter_config and rejects any
      // smuggled fields with 422 (Pydantic extra="forbid"). Defense in depth:
      // the UI doesn't even render those inputs.
      await post("/agents", { name, role });
      onCreated();
    } catch (e) {
      setErr(String(e));
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center">
      <div className="bg-white rounded-lg p-6 w-96">
        <h2 className="text-lg font-semibold mb-4">New agent</h2>
        <label className="block mb-3">
          <span className="text-sm">Name</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full border rounded px-3 py-2 mt-1"
          />
        </label>
        <label className="block mb-4">
          <span className="text-sm">Role</span>
          <select
            value={role}
            onChange={(e) => setRole(e.target.value)}
            className="w-full border rounded px-3 py-2 mt-1"
          >
            <option value="engineer">Engineer</option>
            <option value="ceo">CEO</option>
            <option value="manager">Manager</option>
          </select>
        </label>
        {err && <div className="text-red-600 text-sm mb-2">{err}</div>}
        <div className="flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-3 py-1 border rounded"
          >
            Cancel
          </button>
          <button
            onClick={submit}
            disabled={submitting || !name}
            className="px-3 py-1 bg-zinc-900 text-white rounded"
          >
            {submitting ? "Creating…" : "Create"}
          </button>
        </div>
      </div>
    </div>
  );
}
