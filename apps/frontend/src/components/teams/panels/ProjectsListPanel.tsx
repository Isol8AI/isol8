"use client";

import { useState } from "react";
import { useTeamsApi } from "@/hooks/useTeamsApi";

interface Project {
  id: string;
  name: string;
  description?: string;
  budget_monthly_cents?: number;
}

export function ProjectsListPanel() {
  const { read } = useTeamsApi();
  const { data, isLoading, error, mutate } = read<{ projects: Project[] }>(
    "/projects",
  );
  const [creating, setCreating] = useState(false);

  if (isLoading) return <div className="p-8">Loading…</div>;
  if (error) return <div className="p-8 text-red-600">Error: {String(error)}</div>;

  return (
    <div className="p-8 max-w-4xl">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-semibold">Projects</h1>
        <button
          onClick={() => setCreating(true)}
          className="px-4 py-2 bg-zinc-900 text-white rounded text-sm"
        >
          New project
        </button>
      </div>

      <ul className="divide-y border rounded">
        {(data?.projects ?? []).map((p) => (
          <li
            key={p.id}
            className="flex justify-between items-center p-4"
          >
            <div>
              <div className="font-medium">{p.name}</div>
              {p.description && (
                <div className="text-xs text-zinc-500">{p.description}</div>
              )}
            </div>
            <a
              href={`/teams/projects/${p.id}`}
              className="text-sm text-zinc-600 hover:underline"
            >
              Open →
            </a>
          </li>
        ))}
        {(data?.projects ?? []).length === 0 && (
          <li className="p-4 text-sm text-zinc-500">No projects yet.</li>
        )}
      </ul>

      {creating && (
        <CreateProjectDialog
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

function CreateProjectDialog({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const { post } = useTeamsApi();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit() {
    setSubmitting(true);
    setErr(null);
    try {
      // CreateProjectBody (Task 3): name (req), description?
      const body: Record<string, unknown> = { name };
      if (description) body.description = description;
      await post("/projects", body);
      onCreated();
    } catch (e) {
      setErr(String(e));
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center">
      <div className="bg-white rounded-lg p-6 w-96">
        <h2 className="text-lg font-semibold mb-4">New project</h2>
        <label className="block mb-3">
          <span className="text-sm">Name</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full border rounded px-3 py-2 mt-1"
          />
        </label>
        <label className="block mb-4">
          <span className="text-sm">Description</span>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="w-full border rounded px-3 py-2 mt-1"
            rows={3}
          />
        </label>
        {err && <div className="text-red-600 text-sm mb-2">{err}</div>}
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="px-3 py-1 border rounded">
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
