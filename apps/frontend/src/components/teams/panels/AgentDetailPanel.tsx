"use client";

import { Loader2, ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { usePaperclipApi, usePaperclipMutation } from "@/hooks/usePaperclip";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useRouter } from "next/navigation";

interface AgentRun {
  id?: string;
  status?: string;
  cost?: number;
  model?: string;
  created_at?: string;
}

interface AgentDetail {
  id?: string;
  name?: string;
  role?: string;
  status?: string;
  adapter_type?: string;
  adapter_config?: Record<string, unknown>;
  capabilities?: string[];
  last_heartbeat?: string;
  runs?: AgentRun[];
  budget?: {
    limit?: number;
    used?: number;
  };
}

type TabKey = "overview" | "runs" | "configuration" | "budget";

interface AgentDetailPanelProps {
  agentId?: string;
  isNew?: boolean;
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

function NewAgentForm() {
  const router = useRouter();
  const mutation = usePaperclipMutation();
  const [name, setName] = useState("");
  const [role, setRole] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    setError(null);
    try {
      await mutation.post("agents", {
        name,
        role,
        adapter_type: "openclaw",
        adapter_config: {
          url: "ws://localhost:18789",
        },
      });
      router.push("/teams/agents");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create agent");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center gap-2">
        <Link href="/teams/agents">
          <Button variant="ghost" size="sm">
            <ArrowLeft className="h-4 w-4 mr-1" />
            Back
          </Button>
        </Link>
        <h1 className="text-lg font-semibold text-[#1a1a1a]">New Agent</h1>
      </div>

      <div className="rounded-lg border border-[#e5e0d5] bg-white p-6 max-w-lg">
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1">
            <label className="text-xs font-medium text-[#8a8578]">Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Agent name"
              required
              className="w-full px-3 py-2 text-sm rounded-md border border-[#e5e0d5] bg-white focus:outline-none focus:ring-2 focus:ring-[#1a1a1a]/10"
            />
          </div>
          <div className="space-y-1">
            <label className="text-xs font-medium text-[#8a8578]">Role</label>
            <input
              type="text"
              value={role}
              onChange={(e) => setRole(e.target.value)}
              placeholder="e.g. Support Agent, Research Assistant"
              className="w-full px-3 py-2 text-sm rounded-md border border-[#e5e0d5] bg-white focus:outline-none focus:ring-2 focus:ring-[#1a1a1a]/10"
            />
          </div>
          <div className="space-y-1">
            <label className="text-xs font-medium text-[#8a8578]">Adapter</label>
            <div className="px-3 py-2 text-sm rounded-md border border-[#e5e0d5] bg-[#f5f3ee] text-[#8a8578]">
              OpenClaw Gateway — ws://localhost:18789
            </div>
          </div>
          {error && <p className="text-xs text-red-600">{error}</p>}
          <Button type="submit" disabled={isSubmitting || !name} size="sm">
            {isSubmitting && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
            Create Agent
          </Button>
        </form>
      </div>
    </div>
  );
}

export function AgentDetailPanel({ agentId, isNew }: AgentDetailPanelProps) {
  const [activeTab, setActiveTab] = useState<TabKey>("overview");
  const { data: agent, isLoading } = usePaperclipApi<AgentDetail>(
    !isNew && agentId ? `agents/${agentId}` : null,
  );

  if (isNew) return <NewAgentForm />;

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-[#8a8578]" />
      </div>
    );
  }

  if (!agent) {
    return (
      <div className="p-6 text-sm text-[#8a8578]">Agent not found.</div>
    );
  }

  const TABS: { key: TabKey; label: string }[] = [
    { key: "overview", label: "Overview" },
    { key: "runs", label: "Runs" },
    { key: "configuration", label: "Configuration" },
    { key: "budget", label: "Budget" },
  ];

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center gap-2">
        <Link href="/teams/agents">
          <Button variant="ghost" size="sm">
            <ArrowLeft className="h-4 w-4 mr-1" />
            Back
          </Button>
        </Link>
        <div>
          <h1 className="text-lg font-semibold text-[#1a1a1a]">{agent.name ?? "Agent"}</h1>
          {agent.role && <p className="text-sm text-[#8a8578]">{agent.role}</p>}
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-[#e5e0d5]">
        {TABS.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setActiveTab(key)}
            className={cn(
              "px-3 py-2 text-sm font-medium transition-colors border-b-2 -mb-px",
              activeTab === key
                ? "border-[#1a1a1a] text-[#1a1a1a]"
                : "border-transparent text-[#8a8578] hover:text-[#1a1a1a]",
            )}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === "overview" && (
        <div className="rounded-lg border border-[#e5e0d5] bg-white p-4 space-y-3">
          <Row label="Status" value={agent.status ?? "—"} />
          <Row label="Adapter" value={agent.adapter_type ?? "—"} />
          <Row label="Last Heartbeat" value={formatTime(agent.last_heartbeat)} />
          {agent.capabilities && agent.capabilities.length > 0 && (
            <div>
              <span className="text-xs text-[#8a8578]">Capabilities</span>
              <div className="mt-1 flex flex-wrap gap-1">
                {agent.capabilities.map((cap) => (
                  <span key={cap} className="text-xs bg-[#f5f3ee] text-[#1a1a1a] px-2 py-0.5 rounded-full">
                    {cap}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {activeTab === "runs" && (
        <div>
          {!agent.runs || agent.runs.length === 0 ? (
            <div className="rounded-lg border border-[#e5e0d5] bg-white p-8 text-center">
              <p className="text-sm text-[#8a8578]">No runs yet</p>
            </div>
          ) : (
            <div className="rounded-lg border border-[#e5e0d5] bg-white divide-y divide-[#e5e0d5]">
              {agent.runs.map((run, idx) => (
                <div key={run.id ?? idx} className="px-4 py-3 flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <span
                      className={cn(
                        "h-2 w-2 rounded-full",
                        run.status === "completed" ? "bg-[#2d8a4e]" :
                        run.status === "running" ? "bg-blue-500 animate-pulse" :
                        run.status === "error" ? "bg-red-500" :
                        "bg-[#b0a99a]",
                      )}
                    />
                    <span className="text-sm text-[#1a1a1a]">{run.status ?? "—"}</span>
                  </div>
                  <div className="flex items-center gap-3 text-xs text-[#8a8578]">
                    {run.model && <span>{run.model}</span>}
                    {run.cost !== undefined && <span>${run.cost.toFixed(4)}</span>}
                    <span>{formatTime(run.created_at)}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {activeTab === "configuration" && (
        <div className="rounded-lg border border-[#e5e0d5] bg-white p-4">
          <pre className="text-xs text-[#1a1a1a] overflow-auto whitespace-pre-wrap">
            {JSON.stringify(agent.adapter_config ?? {}, null, 2)}
          </pre>
        </div>
      )}

      {activeTab === "budget" && (
        <div className="rounded-lg border border-[#e5e0d5] bg-white p-4 space-y-3">
          <Row label="Budget Limit" value={agent.budget?.limit !== undefined ? `$${agent.budget.limit.toFixed(2)}` : "—"} />
          <Row label="Used" value={agent.budget?.used !== undefined ? `$${agent.budget.used.toFixed(2)}` : "—"} />
          {agent.budget?.limit !== undefined && agent.budget?.used !== undefined && (
            <div>
              <div className="flex justify-between text-xs text-[#8a8578] mb-1">
                <span>Usage</span>
                <span>{Math.round((agent.budget.used / agent.budget.limit) * 100)}%</span>
              </div>
              <div className="h-2 rounded-full bg-[#f5f3ee] overflow-hidden">
                <div
                  className="h-full bg-[#1a1a1a] rounded-full"
                  style={{ width: `${Math.min(100, (agent.budget.used / agent.budget.limit) * 100)}%` }}
                />
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-[#8a8578]">{label}</span>
      <span className="font-medium text-[#1a1a1a]">{value}</span>
    </div>
  );
}

