"use client";

import { useAuth } from "@clerk/nextjs";
import useSWR from "swr";
import { useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "https://api.isol8.co";

interface AgentSummary {
  agent_id: string;
  name: string | null;
  updated_at: string | null;
}

interface UploadResponse {
  listing_id: string;
  manifest_sha256: string;
  file_count: number;
  bytes: number;
}

interface Props {
  listingId: string;
  onSelected?: (resp: UploadResponse) => void;
}

/**
 * Lists the seller's existing OpenClaw agents from EFS via /my-agents,
 * then on selection POSTs /artifact-from-agent which snapshots the
 * picked agent into the listing's S3 artifact.
 *
 * Empty state when no container or no agents.
 */
export function AgentPicker({ listingId, onSelected }: Props) {
  const { getToken } = useAuth();
  const [picking, setPicking] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  const { data, error, isLoading } = useSWR<{ items: AgentSummary[] }>(
    `${API}/api/v1/marketplace/my-agents`,
    async (url: string) => {
      const jwt = await getToken();
      const resp = await fetch(url, {
        headers: { Authorization: `Bearer ${jwt}` },
      });
      if (!resp.ok) throw new Error(`failed (${resp.status})`);
      return resp.json();
    },
  );

  async function publishAgent(agentId: string) {
    setPicking(agentId);
    setStatus("Snapshotting agent…");
    try {
      const jwt = await getToken();
      const resp = await fetch(
        `${API}/api/v1/marketplace/listings/${encodeURIComponent(listingId)}/artifact-from-agent`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${jwt}`,
            "content-type": "application/json",
          },
          body: JSON.stringify({ agent_id: agentId }),
        },
      );
      if (resp.ok) {
        const body = (await resp.json()) as UploadResponse;
        setStatus(`Snapshot complete (${body.file_count} files).`);
        onSelected?.(body);
      } else {
        const txt = await resp.text();
        setStatus(`Snapshot failed (${resp.status}): ${txt.slice(0, 200)}`);
      }
    } catch (e) {
      setStatus(`Snapshot failed: ${e instanceof Error ? e.message : "unknown"}`);
    } finally {
      setPicking(null);
    }
  }

  if (isLoading) return <p className="text-sm text-zinc-400">Loading agents…</p>;
  if (error) return <p className="text-sm text-zinc-400">Could not load agents.</p>;

  const items = data?.items ?? [];
  if (items.length === 0) {
    return (
      <p className="text-sm text-zinc-400">
        No agents found in your container. Create one in the chat app, then come back.
      </p>
    );
  }

  return (
    <div className="rounded-lg border border-zinc-800 p-4 space-y-3">
      <p className="text-sm text-zinc-400">
        Pick one of your existing agents to snapshot for this listing. Edits to
        the agent after publishing don&apos;t affect already-purchased copies.
      </p>
      <ul className="space-y-2">
        {items.map((a) => (
          <li
            key={a.agent_id}
            className="flex items-center justify-between rounded border border-zinc-800 px-3 py-2"
          >
            <div>
              <p className="text-sm font-medium text-zinc-100">{a.name ?? a.agent_id}</p>
              <p className="text-xs text-zinc-500">{a.agent_id}</p>
            </div>
            <button
              type="button"
              onClick={() => publishAgent(a.agent_id)}
              disabled={picking !== null}
              className="text-sm px-3 py-1 rounded bg-zinc-100 text-zinc-950 disabled:opacity-50"
            >
              {picking === a.agent_id ? "Picking…" : "Use this agent"}
            </button>
          </li>
        ))}
      </ul>
      {status && <p className="text-sm text-zinc-300">{status}</p>}
    </div>
  );
}
