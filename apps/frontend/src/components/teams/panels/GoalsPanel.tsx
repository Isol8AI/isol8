"use client";

import { useState, useMemo } from "react";
import { useTeamsApi } from "@/hooks/useTeamsApi";

interface Goal {
  id: string;
  title: string;
  description?: string;
  parent_id?: string | null;
  status?: string;
}

interface GoalNode extends Goal {
  children: GoalNode[];
}

function buildTree(goals: Goal[]): GoalNode[] {
  const byId: Record<string, GoalNode> = {};
  goals.forEach((g) => {
    byId[g.id] = { ...g, children: [] };
  });
  const roots: GoalNode[] = [];
  goals.forEach((g) => {
    const node = byId[g.id];
    if (g.parent_id && byId[g.parent_id]) {
      byId[g.parent_id].children.push(node);
    } else {
      roots.push(node);
    }
  });
  return roots;
}

function GoalRow({ node, depth }: { node: GoalNode; depth: number }) {
  return (
    <>
      <li
        className="p-3 border-b last:border-b-0"
        style={{ paddingLeft: `${depth * 1.5 + 0.75}rem` }}
      >
        <div className="font-medium">{node.title}</div>
        {node.description && (
          <div className="text-xs text-zinc-500 mt-0.5">{node.description}</div>
        )}
      </li>
      {node.children.map((c) => (
        <GoalRow key={c.id} node={c} depth={depth + 1} />
      ))}
    </>
  );
}

export function GoalsPanel() {
  const { read } = useTeamsApi();
  const { data, isLoading, error, mutate } = read<{ goals: Goal[] }>("/goals");
  const [creating, setCreating] = useState(false);

  const tree = useMemo(() => buildTree(data?.goals ?? []), [data]);

  if (isLoading) return <div className="p-8">Loading…</div>;
  if (error) return <div className="p-8 text-red-600">Error: {String(error)}</div>;

  return (
    <div className="p-8 max-w-4xl">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-semibold">Goals</h1>
        <button
          onClick={() => setCreating(true)}
          className="px-4 py-2 bg-zinc-900 text-white rounded text-sm"
        >
          New goal
        </button>
      </div>

      <ul className="border rounded">
        {tree.map((root) => (
          <GoalRow key={root.id} node={root} depth={0} />
        ))}
        {tree.length === 0 && (
          <li className="p-4 text-sm text-zinc-500">No goals yet.</li>
        )}
      </ul>

      {creating && (
        <CreateGoalDialog
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

function CreateGoalDialog({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const { post } = useTeamsApi();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [parentId, setParentId] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit() {
    setSubmitting(true);
    setErr(null);
    try {
      // CreateGoalBody fields (Task 3): title, description?, parent_id?
      const body: Record<string, unknown> = { title };
      if (description) body.description = description;
      if (parentId) body.parent_id = parentId;
      await post("/goals", body);
      onCreated();
    } catch (e) {
      setErr(String(e));
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center">
      <div className="bg-white rounded-lg p-6 w-[28rem]">
        <h2 className="text-lg font-semibold mb-4">New goal</h2>
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
        <label className="block mb-4">
          <span className="text-sm">Parent goal ID (optional)</span>
          <input
            value={parentId}
            onChange={(e) => setParentId(e.target.value)}
            className="w-full border rounded px-3 py-2 mt-1"
          />
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
