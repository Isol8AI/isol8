"use client";

import { Loader2, Network } from "lucide-react";
import { usePaperclipApi } from "@/hooks/usePaperclip";
import { cn } from "@/lib/utils";

interface Agent {
  id?: string;
  name?: string;
  role?: string;
  status?: string;
  reports_to?: string;
}

function StatusDot({ status }: { status?: string }) {
  return (
    <span
      className={cn(
        "h-2 w-2 rounded-full flex-shrink-0 inline-block",
        status === "active" ? "bg-[#2d8a4e]" :
        status === "paused" ? "bg-yellow-400" :
        status === "error" ? "bg-red-500" :
        "bg-[#b0a99a]",
      )}
    />
  );
}

function buildTree(agents: Agent[]): Array<Agent & { children: Agent[] }> {
  const map = new Map<string, Agent & { children: Agent[] }>();
  const roots: Array<Agent & { children: Agent[] }> = [];

  for (const agent of agents) {
    map.set(agent.id ?? "", { ...agent, children: [] });
  }

  for (const agent of agents) {
    const node = map.get(agent.id ?? "")!;
    if (agent.reports_to && map.has(agent.reports_to)) {
      map.get(agent.reports_to)!.children.push(node);
    } else {
      roots.push(node);
    }
  }

  return roots;
}

function AgentNode({ agent, depth = 0 }: { agent: Agent & { children: Agent[] }; depth?: number }) {
  return (
    <div className={depth > 0 ? "ml-5 border-l border-[#e5e0d5] pl-3" : ""}>
      <div className="flex items-center gap-2 py-2">
        <StatusDot status={agent.status} />
        <span className="text-sm font-medium text-[#1a1a1a]">{agent.name ?? "Unnamed"}</span>
        {agent.role && (
          <span className="text-xs text-[#b0a99a]">{agent.role}</span>
        )}
      </div>
      {agent.children.map((child) => (
        <AgentNode key={child.id} agent={child as Agent & { children: Agent[] }} depth={depth + 1} />
      ))}
    </div>
  );
}

export function OrgChartPanel() {
  const { data, isLoading } = usePaperclipApi<Agent[]>("agents");

  const agents = Array.isArray(data) ? data : [];
  const tree = buildTree(agents);

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-[#8a8578]" />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-[#1a1a1a]">Org Chart</h1>
        <p className="text-sm text-[#8a8578]">Agent reporting structure</p>
      </div>

      {agents.length === 0 ? (
        <div className="rounded-lg border border-[#e5e0d5] bg-white p-8 text-center">
          <Network className="h-6 w-6 text-[#b0a99a] mx-auto mb-2" />
          <p className="text-sm text-[#8a8578]">No agents found</p>
        </div>
      ) : (
        <div className="rounded-lg border border-[#e5e0d5] bg-white px-4 py-2">
          {tree.map((agent) => (
            <AgentNode key={agent.id} agent={agent} />
          ))}
        </div>
      )}
    </div>
  );
}
