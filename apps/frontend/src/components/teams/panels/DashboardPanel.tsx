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
}

export function DashboardPanel() {
  const { read } = useTeamsApi();
  const { data, isLoading, error } = read<DashboardResponse>("/dashboard");

  if (isLoading) return <div className="p-8">Loading…</div>;
  if (error) return <div className="p-8 text-red-600">Error: {String(error)}</div>;

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
