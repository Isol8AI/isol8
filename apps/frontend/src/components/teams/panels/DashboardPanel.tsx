"use client";

import { Loader2, Bot, Activity, DollarSign, CheckCircle2 } from "lucide-react";
import Link from "next/link";
import { usePaperclipApi } from "@/hooks/usePaperclip";

interface DashboardData {
  agents_count?: number;
  tasks_in_progress?: number;
  month_spend?: number;
  pending_approvals?: number;
  recent_activity?: Array<{
    id?: string;
    description?: string;
    timestamp?: string;
  }>;
}

function formatCurrency(amount?: number) {
  if (amount === undefined) return "—";
  return `$${amount.toFixed(2)}`;
}

function formatTime(ts?: string) {
  if (!ts) return "—";
  const date = new Date(ts);
  const ago = Date.now() - date.getTime();
  const minutes = Math.floor(ago / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function DashboardPanel() {
  const { data, isLoading } = usePaperclipApi<DashboardData>("dashboard");

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-[#8a8578]" />
      </div>
    );
  }

  const metrics = [
    {
      label: "Agents",
      value: data?.agents_count ?? "—",
      icon: Bot,
      href: "/teams/agents",
    },
    {
      label: "Tasks In Progress",
      value: data?.tasks_in_progress ?? "—",
      icon: Activity,
      href: "/teams/issues",
    },
    {
      label: "Month Spend",
      value: formatCurrency(data?.month_spend),
      icon: DollarSign,
      href: "/teams/costs",
    },
    {
      label: "Pending Approvals",
      value: data?.pending_approvals ?? "—",
      icon: CheckCircle2,
      href: "/teams/approvals",
    },
  ];

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-[#1a1a1a]">Dashboard</h1>
        <p className="text-sm text-[#8a8578]">Overview of your AI agent team.</p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {metrics.map(({ label, value, icon: Icon, href }) => (
          <Link key={label} href={href}>
            <div className="rounded-lg border border-[#e5e0d5] bg-white p-4 hover:shadow-sm transition-shadow cursor-pointer">
              <div className="flex items-center gap-2 mb-2">
                <Icon className="h-4 w-4 text-[#8a8578]" />
                <span className="text-xs text-[#8a8578]">{label}</span>
              </div>
              <div className="text-xl font-semibold text-[#1a1a1a]">{String(value)}</div>
            </div>
          </Link>
        ))}
      </div>

      {data?.recent_activity && data.recent_activity.length > 0 && (
        <div className="space-y-2">
          <h2 className="text-sm font-semibold text-[#1a1a1a]">Recent Activity</h2>
          <div className="rounded-lg border border-[#e5e0d5] bg-white divide-y divide-[#e5e0d5]">
            {data.recent_activity.map((item, idx) => (
              <div key={item.id ?? idx} className="px-4 py-3 flex items-center justify-between">
                <span className="text-sm text-[#1a1a1a]">{item.description ?? "—"}</span>
                <span className="text-xs text-[#b0a99a]">{formatTime(item.timestamp)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {(!data?.recent_activity || data.recent_activity.length === 0) && (
        <div className="rounded-lg border border-[#e5e0d5] bg-white p-8 text-center">
          <Activity className="h-6 w-6 text-[#b0a99a] mx-auto mb-2" />
          <p className="text-sm text-[#8a8578]">No recent activity</p>
        </div>
      )}
    </div>
  );
}
