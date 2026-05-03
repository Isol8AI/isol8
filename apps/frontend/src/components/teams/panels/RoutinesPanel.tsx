"use client";

import { useState } from "react";
import { useTeamsApi } from "@/hooks/useTeamsApi";

interface Routine {
  id: string;
  name: string;
  cron: string;
  agent_id: string;
  prompt?: string;
  enabled: boolean;
}

export function RoutinesPanel() {
  const { read, patch, del } = useTeamsApi();
  const { data, isLoading, error, mutate } = read<{ routines: Routine[] }>(
    "/routines",
  );
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  if (isLoading) return <div className="p-8">Loading…</div>;
  if (error) return <div className="p-8 text-red-600">Error: {String(error)}</div>;

  async function toggle(id: string, enabled: boolean) {
    setBusy(id);
    try {
      // PatchRoutineBody whitelists `enabled` (Task 3).
      await patch(`/routines/${id}`, { enabled });
      mutate();
    } finally {
      setBusy(null);
    }
  }
  async function remove(id: string) {
    if (!confirm("Delete this routine?")) return;
    setBusy(id);
    try {
      await del(`/routines/${id}`);
      mutate();
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="p-8 max-w-4xl">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-semibold">Routines</h1>
        <button
          onClick={() => setCreating(true)}
          className="px-4 py-2 bg-zinc-900 text-white rounded text-sm"
        >
          New routine
        </button>
      </div>

      <ul className="divide-y border rounded">
        {(data?.routines ?? []).map((r) => (
          <li
            key={r.id}
            className="flex justify-between items-center p-4 gap-3"
          >
            <div>
              <div className="font-medium">{r.name}</div>
              <div className="text-xs text-zinc-500">
                {r.cron} · agent {r.agent_id}
              </div>
            </div>
            <div className="flex items-center gap-3">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={r.enabled}
                  disabled={busy === r.id}
                  onChange={(e) => toggle(r.id, e.target.checked)}
                />
                <span>{r.enabled ? "Enabled" : "Disabled"}</span>
              </label>
              <button
                onClick={() => remove(r.id)}
                disabled={busy === r.id}
                className="text-sm text-zinc-500 hover:underline"
              >
                Delete
              </button>
            </div>
          </li>
        ))}
        {(data?.routines ?? []).length === 0 && (
          <li className="p-4 text-sm text-zinc-500">No routines yet.</li>
        )}
      </ul>

      {creating && (
        <CreateRoutineDialog
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

function CreateRoutineDialog({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const { post } = useTeamsApi();
  const [name, setName] = useState("");
  const [cron, setCron] = useState("0 9 * * *");
  const [agentId, setAgentId] = useState("");
  const [prompt, setPrompt] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit() {
    setSubmitting(true);
    setErr(null);
    try {
      // CreateRoutineBody fields (Task 3): name, cron, agent_id, prompt, enabled.
      await post("/routines", {
        name,
        cron,
        agent_id: agentId,
        prompt,
        enabled,
      });
      onCreated();
    } catch (e) {
      setErr(String(e));
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center">
      <div className="bg-white rounded-lg p-6 w-[28rem]">
        <h2 className="text-lg font-semibold mb-4">New routine</h2>
        <label className="block mb-3">
          <span className="text-sm">Name</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full border rounded px-3 py-2 mt-1"
          />
        </label>
        <label className="block mb-3">
          <span className="text-sm">Cron</span>
          <input
            value={cron}
            onChange={(e) => setCron(e.target.value)}
            className="w-full border rounded px-3 py-2 mt-1 font-mono"
          />
        </label>
        <label className="block mb-3">
          <span className="text-sm">Agent ID</span>
          <input
            value={agentId}
            onChange={(e) => setAgentId(e.target.value)}
            className="w-full border rounded px-3 py-2 mt-1"
          />
        </label>
        <label className="block mb-3">
          <span className="text-sm">Prompt</span>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            className="w-full border rounded px-3 py-2 mt-1"
            rows={3}
          />
        </label>
        <label className="flex items-center gap-2 mb-4 text-sm">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
          />
          <span>Enabled</span>
        </label>
        {err && <div className="text-red-600 text-sm mb-2">{err}</div>}
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="px-3 py-1 border rounded">
            Cancel
          </button>
          <button
            onClick={submit}
            disabled={submitting || !name || !cron || !agentId || !prompt}
            className="px-3 py-1 bg-zinc-900 text-white rounded"
          >
            {submitting ? "Creating…" : "Create"}
          </button>
        </div>
      </div>
    </div>
  );
}
