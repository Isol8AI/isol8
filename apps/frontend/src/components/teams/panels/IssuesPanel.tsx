"use client";

import { useState } from "react";
import { useTeamsApi } from "@/hooks/useTeamsApi";
import type { IssuePriority } from "@/components/teams/shared/types";

interface Issue {
  id: string;
  title: string;
  status?: string;
  priority?: string;
  project_id?: string;
  assignee_agent_id?: string;
}

export function IssuesPanel() {
  const { read } = useTeamsApi();
  const { data, isLoading, error, mutate } = read<{ issues: Issue[] }>(
    "/issues",
  );
  const [creating, setCreating] = useState(false);

  if (isLoading) return <div className="p-8">Loading…</div>;
  if (error) return <div className="p-8 text-red-600">Error: {String(error)}</div>;

  return (
    <div className="p-8 max-w-4xl">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-semibold">Issues</h1>
        <button
          onClick={() => setCreating(true)}
          className="px-4 py-2 bg-zinc-900 text-white rounded text-sm"
        >
          New issue
        </button>
      </div>

      <ul className="divide-y border rounded">
        {(data?.issues ?? []).map((it) => (
          <li
            key={it.id}
            className="flex justify-between items-center p-4"
          >
            <div>
              <div className="font-medium">{it.title}</div>
              <div className="text-xs text-zinc-500">
                {it.status ?? "open"}
                {it.priority ? ` · ${it.priority}` : ""}
              </div>
            </div>
            <a
              href={`/teams/issues/${it.id}`}
              className="text-sm text-zinc-600 hover:underline"
            >
              Open →
            </a>
          </li>
        ))}
        {(data?.issues ?? []).length === 0 && (
          <li className="p-4 text-sm text-zinc-500">No issues yet.</li>
        )}
      </ul>

      {creating && (
        <CreateIssueDialog
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

function CreateIssueDialog({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const { post } = useTeamsApi();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [projectId, setProjectId] = useState("");
  const [assigneeAgentId, setAssigneeAgentId] = useState("");
  const [priority, setPriority] = useState<IssuePriority | "">("");
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit() {
    setSubmitting(true);
    setErr(null);
    try {
      // Body fields match CreateIssueBody (Pydantic, extra="forbid"):
      // title (req), description?, project_id?, assignee_agent_id?, priority?
      const body: Record<string, unknown> = { title };
      if (description) body.description = description;
      if (projectId) body.project_id = projectId;
      if (assigneeAgentId) body.assignee_agent_id = assigneeAgentId;
      if (priority) body.priority = priority;
      await post("/issues", body);
      onCreated();
    } catch (e) {
      setErr(String(e));
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center">
      <div className="bg-white rounded-lg p-6 w-[28rem]">
        <h2 className="text-lg font-semibold mb-4">New issue</h2>
        <label className="block mb-3">
          <span className="text-sm">Title</span>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="w-full border rounded px-3 py-2 mt-1"
          />
        </label>
        <label className="block mb-3">
          <span className="text-sm">Description</span>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="w-full border rounded px-3 py-2 mt-1"
            rows={3}
          />
        </label>
        <label className="block mb-3">
          <span className="text-sm">Project ID (optional)</span>
          <input
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
            className="w-full border rounded px-3 py-2 mt-1"
          />
        </label>
        <label className="block mb-3">
          <span className="text-sm">Assignee agent ID (optional)</span>
          <input
            value={assigneeAgentId}
            onChange={(e) => setAssigneeAgentId(e.target.value)}
            className="w-full border rounded px-3 py-2 mt-1"
          />
        </label>
        <label className="block mb-4">
          <span className="text-sm">Priority</span>
          <select
            value={priority}
            onChange={(e) => setPriority(e.target.value as IssuePriority | "")}
            className="w-full border rounded px-3 py-2 mt-1"
          >
            <option value="">None</option>
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
            <option value="critical">Critical</option>
          </select>
        </label>
        {err && <div className="text-red-600 text-sm mb-2">{err}</div>}
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="px-3 py-1 border rounded">
            Cancel
          </button>
          <button
            onClick={submit}
            disabled={submitting || !title}
            className="px-3 py-1 bg-zinc-900 text-white rounded"
          >
            {submitting ? "Creating…" : "Create"}
          </button>
        </div>
      </div>
    </div>
  );
}
