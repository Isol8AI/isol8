"use client";

import { useTeamsApi } from "@/hooks/useTeamsApi";

interface DashboardData {
  agents?: number;
  openIssues?: number;
  runsToday?: number;
  spendCents?: number;
}

interface DashboardResponse {
  dashboard?: DashboardData;
  sidebar_badges?: Record<string, number>;
  // BFF returns ``{detail}`` envelopes for non-200 status codes that
  // the fetch layer still surfaces as success bodies (202 in particular —
  // ``response.ok`` is true for any 2xx, so SWR sees the JSON body
  // without throwing). We use this to detect the lazy-provision
  // "still setting up" state and auto-poll.
  detail?: string;
}

interface ApiError extends Error {
  status?: number;
  detail?: string;
}

const PROVISIONING_DETAIL = "team workspace provisioning";

export function DashboardPanel() {
  const { read } = useTeamsApi();
  const { data, isLoading, error } = read<DashboardResponse>("/dashboard", {
    refreshInterval: (latest) =>
      latest && (latest as DashboardResponse).detail === PROVISIONING_DETAIL ? 3000 : 0,
  });

  if (isLoading) return <div className="p-8">Loading…</div>;

  if (data?.detail === PROVISIONING_DETAIL) {
    return (
      <div className="p-8">
        <h1 className="text-2xl font-semibold mb-2">Setting up your Teams workspace…</h1>
        <p className="text-zinc-600">
          This usually takes about 30 seconds. The page will refresh automatically.
        </p>
      </div>
    );
  }

  if (error) {
    const apiErr = error as ApiError;
    if (apiErr.status === 402) {
      return (
        <div className="p-8">
          <h1 className="text-2xl font-semibold mb-2">Subscribe to enable Teams</h1>
          <p className="text-zinc-600">
            Teams runs on top of your agent container. Start a subscription from the chat
            page first, then come back.
          </p>
        </div>
      );
    }
    return <div className="p-8 text-red-600">Error: {String(error)}</div>;
  }

  const d = data?.dashboard ?? {};
  return (
    <div className="p-8 max-w-5xl">
      <h1 className="text-2xl font-semibold mb-6">Overview</h1>
      <div className="grid grid-cols-4 gap-4">
        <Card label="Agents" value={d.agents ?? 0} />
        <Card label="Open issues" value={d.openIssues ?? 0} />
        <Card label="Runs today" value={d.runsToday ?? 0} />
        <Card label="Spend ($)" value={((d.spendCents ?? 0) / 100).toFixed(2)} />
      </div>
    </div>
  );
}

function Card({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="border rounded p-4 bg-white">
      <div className="text-xs text-zinc-500">{label}</div>
      <div className="text-2xl font-semibold mt-1">{value}</div>
    </div>
  );
}
