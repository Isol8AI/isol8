"use client";

import { Loader2, DollarSign } from "lucide-react";
import { usePaperclipApi } from "@/hooks/usePaperclip";

interface AgentCost {
  agent_id?: string;
  agent_name?: string;
  month_spend?: number;
  total_spend?: number;
}

interface CostsData {
  month_spend?: number;
  all_time_spend?: number;
  by_agent?: AgentCost[];
}

function fmt(amount?: number) {
  if (amount === undefined) return "—";
  return `$${amount.toFixed(2)}`;
}

export function CostsPanel() {
  const { data, isLoading } = usePaperclipApi<CostsData>("costs");

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-[#8a8578]" />
      </div>
    );
  }

  const byAgent = data?.by_agent ?? [];

  return (
    <div className="p-6 space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-[#1a1a1a]">Costs</h1>
        <p className="text-sm text-[#8a8578]">AI agent spending overview</p>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-lg border border-[#e5e0d5] bg-white p-4">
          <div className="flex items-center gap-2 mb-2">
            <DollarSign className="h-4 w-4 text-[#8a8578]" />
            <span className="text-xs text-[#8a8578]">This Month</span>
          </div>
          <div className="text-xl font-semibold text-[#1a1a1a]">{fmt(data?.month_spend)}</div>
        </div>
        <div className="rounded-lg border border-[#e5e0d5] bg-white p-4">
          <div className="flex items-center gap-2 mb-2">
            <DollarSign className="h-4 w-4 text-[#8a8578]" />
            <span className="text-xs text-[#8a8578]">All Time</span>
          </div>
          <div className="text-xl font-semibold text-[#1a1a1a]">{fmt(data?.all_time_spend)}</div>
        </div>
      </div>

      {byAgent.length > 0 && (
        <div className="space-y-2">
          <h2 className="text-sm font-semibold text-[#1a1a1a]">By Agent</h2>
          <div className="rounded-lg border border-[#e5e0d5] bg-white overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[#e5e0d5] bg-[#faf8f4]">
                  <th className="px-4 py-2 text-left text-xs font-medium text-[#8a8578]">Agent</th>
                  <th className="px-4 py-2 text-right text-xs font-medium text-[#8a8578]">This Month</th>
                  <th className="px-4 py-2 text-right text-xs font-medium text-[#8a8578]">All Time</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#e5e0d5]">
                {byAgent.map((row, idx) => (
                  <tr key={row.agent_id ?? idx}>
                    <td className="px-4 py-2 text-[#1a1a1a]">{row.agent_name ?? row.agent_id ?? "—"}</td>
                    <td className="px-4 py-2 text-right text-[#8a8578]">{fmt(row.month_spend)}</td>
                    <td className="px-4 py-2 text-right text-[#8a8578]">{fmt(row.total_spend)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
