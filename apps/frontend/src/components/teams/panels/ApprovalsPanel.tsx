"use client";

import { useState } from "react";
import { useTeamsApi } from "@/hooks/useTeamsApi";

interface Approval {
  id: string;
  title: string;
  description?: string;
  createdAt?: string;
}

export function ApprovalsPanel() {
  const { read, post } = useTeamsApi();
  const { data, mutate } = read<{ approvals: Approval[] }>("/approvals");
  const [busy, setBusy] = useState<string | null>(null);

  async function approve(id: string) {
    setBusy(id);
    try {
      // SECURITY: body contains ONLY {note}; the BFF whitelists with
      // extra="forbid" via ApproveApprovalBody (Task 3 schema).
      await post(`/approvals/${id}/approve`, { note: "approved via UI" });
      mutate();
    } finally {
      setBusy(null);
    }
  }
  async function reject(id: string) {
    const reason = prompt("Reason for rejection?");
    if (!reason) return;
    setBusy(id);
    try {
      // SECURITY: body contains ONLY {reason}; the BFF whitelists via
      // RejectApprovalBody (Task 3 schema).
      await post(`/approvals/${id}/reject`, { reason });
      mutate();
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="p-8 max-w-4xl">
      <h1 className="text-2xl font-semibold mb-6">Approvals</h1>
      <ul className="space-y-3">
        {(data?.approvals ?? []).map((a) => (
          <li key={a.id} className="border rounded p-4">
            <div className="font-medium">{a.title}</div>
            {a.description && (
              <div className="text-sm text-zinc-600 mt-1">{a.description}</div>
            )}
            <div className="flex gap-2 mt-3">
              <button
                onClick={() => approve(a.id)}
                disabled={busy === a.id}
                className="px-3 py-1 bg-zinc-900 text-white rounded text-sm"
              >
                Approve
              </button>
              <button
                onClick={() => reject(a.id)}
                disabled={busy === a.id}
                className="px-3 py-1 border rounded text-sm"
              >
                Reject
              </button>
            </div>
          </li>
        ))}
        {(data?.approvals ?? []).length === 0 && (
          <li className="text-sm text-zinc-500">No pending approvals.</li>
        )}
      </ul>
    </div>
  );
}
