"use client";

import { Loader2, Bot, Plus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { usePaperclipApi } from "@/hooks/usePaperclip";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface Agent {
  id?: string;
  name?: string;
  role?: string;
  adapter_type?: string;
  status?: "active" | "paused" | "error" | string;
}

type FilterTab = "all" | "active" | "paused" | "error";

function StatusDot({ status }: { status?: string }) {
  return (
    <span
      className={cn(
        "h-2 w-2 rounded-full flex-shrink-0",
        status === "active" ? "bg-[#2d8a4e]" :
        status === "paused" ? "bg-yellow-400" :
        status === "error" ? "bg-red-500" :
        "bg-[#b0a99a]",
      )}
    />
  );
}

export function AgentsPanel() {
  const { data, isLoading } = usePaperclipApi<Agent[]>("agents");
  const [filter, setFilter] = useState<FilterTab>("all");

  const TABS: FilterTab[] = ["all", "active", "paused", "error"];

  const agents = Array.isArray(data) ? data : [];
  const filtered = filter === "all" ? agents : agents.filter((a) => a.status === filter);

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-[#8a8578]" />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-[#1a1a1a]">Agents</h1>
          <p className="text-sm text-[#8a8578]">{agents.length} agent{agents.length !== 1 ? "s" : ""}</p>
        </div>
        <Link href="/teams/agents/new">
          <Button size="sm">
            <Plus className="h-4 w-4 mr-1" />
            New Agent
          </Button>
        </Link>
      </div>

      <div className="flex gap-1">
        {TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setFilter(tab)}
            className={cn(
              "px-3 py-1 rounded-md text-xs font-medium capitalize transition-colors",
              filter === tab
                ? "bg-white text-[#1a1a1a] shadow-sm border border-[#e5e0d5]"
                : "text-[#8a8578] hover:text-[#1a1a1a]",
            )}
          >
            {tab}
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <div className="rounded-lg border border-[#e5e0d5] bg-white p-8 text-center">
          <Bot className="h-6 w-6 text-[#b0a99a] mx-auto mb-2" />
          <p className="text-sm text-[#8a8578]">No agents found</p>
        </div>
      ) : (
        <div className="rounded-lg border border-[#e5e0d5] bg-white divide-y divide-[#e5e0d5]">
          {filtered.map((agent, idx) => (
            <Link key={agent.id ?? idx} href={`/teams/agents/${agent.id}`}>
              <div className="px-4 py-3 flex items-center gap-3 hover:bg-[#faf8f4] transition-colors cursor-pointer">
                <StatusDot status={agent.status} />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-[#1a1a1a] truncate">
                    {agent.name ?? "Unnamed Agent"}
                  </div>
                  <div className="text-xs text-[#8a8578] truncate">{agent.role ?? "—"}</div>
                </div>
                {agent.adapter_type && (
                  <span className="text-xs text-[#b0a99a] bg-[#f5f3ee] px-2 py-0.5 rounded-full flex-shrink-0">
                    {agent.adapter_type}
                  </span>
                )}
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
