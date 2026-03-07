"use client";

import { useState, useCallback } from "react";
import {
  Loader2,
  RefreshCw,
  Search,
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Download,
  Eye,
  EyeOff,
  ExternalLink,
  Wrench,
  Server,
} from "lucide-react";
import { useGatewayRpc, useGatewayRpcMutation } from "@/hooks/useGatewayRpc";
import { useApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { McpServersTab } from "./McpServersTab";

// Map OpenClaw primaryEnv → backend tool_id for BYOK persistence
const ENV_TO_TOOL_ID: Record<string, string> = {
  ELEVENLABS_API_KEY: "elevenlabs",
  OPENAI_API_KEY: "openai_tts",
  PERPLEXITY_API_KEY: "perplexity",
  FIRECRAWL_API_KEY: "firecrawl",
};

type SkillsPanelTab = "skills" | "mcp";

// --- Types matching OpenClaw skills.status response ---

interface SkillInstallSpec {
  id: string;
  kind: string;
  label: string;
  bins: string[];
}

interface SkillStatusEntry {
  name: string;
  description: string;
  source: string;
  skillKey: string;
  emoji?: string;
  primaryEnv?: string;
  bundled?: boolean;
  always: boolean;
  disabled: boolean;
  blockedByAllowlist: boolean;
  eligible: boolean;
  requirements: { bins: string[]; env: string[]; config: string[]; os: string[] };
  missing: { bins: string[]; env: string[]; config: string[]; os: string[] };
  install: SkillInstallSpec[];
  [key: string]: unknown;
}

interface SkillStatusReport {
  workspaceDir?: string;
  managedSkillsDir?: string;
  skills: SkillStatusEntry[];
}

// --- Grouping ---

const SOURCE_ORDER = ["openclaw-bundled", "openclaw-workspace", "openclaw-managed", "openclaw-extra"];
const SOURCE_LABELS: Record<string, string> = {
  "openclaw-bundled": "Built-in",
  "openclaw-workspace": "Workspace",
  "openclaw-managed": "Installed",
  "openclaw-extra": "Extra",
};

function groupBySource(skills: SkillStatusEntry[]): { source: string; label: string; skills: SkillStatusEntry[] }[] {
  const groups = new Map<string, SkillStatusEntry[]>();
  for (const skill of skills) {
    const src = skill.source || "other";
    if (!groups.has(src)) groups.set(src, []);
    groups.get(src)!.push(skill);
  }
  const ordered: { source: string; label: string; skills: SkillStatusEntry[] }[] = [];
  for (const src of SOURCE_ORDER) {
    const g = groups.get(src);
    if (g?.length) {
      ordered.push({ source: src, label: SOURCE_LABELS[src] || src, skills: g });
      groups.delete(src);
    }
  }
  for (const [src, g] of groups) {
    if (g.length) ordered.push({ source: src, label: SOURCE_LABELS[src] || src, skills: g });
  }
  return ordered;
}

// --- Tab definitions ---

const TABS: { id: SkillsPanelTab; label: string; icon: typeof Wrench }[] = [
  { id: "skills", label: "Skills", icon: Wrench },
  { id: "mcp", label: "MCP Servers", icon: Server },
];

// --- Main Panel (tabbed) ---

export function SkillsPanel({ agentId }: { agentId?: string }) {
  const [activeTab, setActiveTab] = useState<SkillsPanelTab>("skills");

  return (
    <div className="flex flex-col h-full">
      {/* Tab bar */}
      <div className="flex border-b border-border px-2">
        {TABS.map((tab) => {
          const Icon = tab.icon;
          return (
            <button
              key={tab.id}
              className={cn(
                "flex items-center gap-1.5 px-3 py-2 text-xs font-medium transition-colors border-b-2 -mb-px",
                activeTab === tab.id
                  ? "border-primary text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground",
              )}
              onClick={() => setActiveTab(tab.id)}
            >
              <Icon className="h-3.5 w-3.5" />
              {tab.label}
            </button>
          );
        })}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto">
        {activeTab === "skills" && <SkillsTab agentId={agentId} />}
        {activeTab === "mcp" && <McpServersTab agentId={agentId} />}
      </div>
    </div>
  );
}

// --- Skills Tab (original SkillsPanel content) ---

function SkillsTab({ agentId }: { agentId?: string }) {
  const params = agentId ? { agentId } : {};
  const { data: raw, error, isLoading, mutate } = useGatewayRpc<SkillStatusReport | SkillStatusEntry[]>(
    "skills.status",
    params,
  );
  const callRpc = useGatewayRpcMutation();
  const api = useApi();
  const [filter, setFilter] = useState("");
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());

  // Normalize response: could be SkillStatusReport or raw array
  const skills: SkillStatusEntry[] = Array.isArray(raw) ? raw : raw?.skills ?? [];

  const filtered = filter
    ? skills.filter(
        (s) =>
          s.name.toLowerCase().includes(filter.toLowerCase()) ||
          s.description?.toLowerCase().includes(filter.toLowerCase()),
      )
    : skills;

  const groups = groupBySource(filtered);

  const toggleGroup = useCallback((source: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(source)) next.delete(source);
      else next.add(source);
      return next;
    });
  }, []);

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 space-y-3">
        <p className="text-sm text-destructive">{error.message}</p>
        <Button variant="outline" size="sm" onClick={() => mutate()}>
          <RefreshCw className="h-3.5 w-3.5 mr-1.5" /> Retry
        </Button>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Skills ({skills.length})</h2>
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="sm" onClick={() => mutate()}>
            <RefreshCw className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="gap-1.5 text-xs"
            onClick={() => window.open("https://clawhub.ai", "_blank")}
          >
            <ExternalLink className="h-3.5 w-3.5" />
            ClawHub
          </Button>
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        Discover more skills on{" "}
        <a href="https://clawhub.ai" target="_blank" rel="noopener noreferrer" className="underline">
          clawhub.ai
        </a>
        . Ask your agent to install them with <code className="text-[11px] bg-muted px-1 rounded">clawhub install &lt;slug&gt;</code>.
      </p>

      {/* Filter */}
      <div className="relative">
        <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
        <Input
          placeholder="Filter skills..."
          className="pl-8 h-8 text-sm"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
      </div>

      {/* Grouped skill cards */}
      {groups.length === 0 && (
        <p className="text-sm text-muted-foreground">No skills found.</p>
      )}

      {groups.map((group) => {
        const collapsed = collapsedGroups.has(group.source);
        return (
          <div key={group.source} className="space-y-2">
            <button
              className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wider text-muted-foreground hover:text-foreground transition-colors"
              onClick={() => toggleGroup(group.source)}
            >
              {collapsed ? (
                <ChevronRight className="h-3 w-3" />
              ) : (
                <ChevronDown className="h-3 w-3" />
              )}
              {group.label} ({group.skills.length})
            </button>

            {!collapsed && (
              <div className="space-y-2">
                {group.skills.map((skill) => (
                  <SkillCard
                    key={skill.skillKey || skill.name}
                    skill={skill}
                    callRpc={callRpc}
                    api={api}
                    onRefresh={mutate}
                  />
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// --- Skill Card ---

function SkillCard({
  skill,
  callRpc,
  api,
  onRefresh,
}: {
  skill: SkillStatusEntry;
  callRpc: <T = unknown>(method: string, params?: Record<string, unknown>) => Promise<T>;
  api: ReturnType<typeof useApi>;
  onRefresh: () => void;
}) {
  const [toggleLoading, setToggleLoading] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [apiKeyVisible, setApiKeyVisible] = useState(false);
  const [saveLoading, setSaveLoading] = useState(false);
  const [saveStatus, setSaveStatus] = useState<"idle" | "success" | "error">("idle");
  const [installLoading, setInstallLoading] = useState<string | null>(null);

  const hasMissing =
    (skill.missing?.bins?.length ?? 0) > 0 ||
    (skill.missing?.env?.length ?? 0) > 0 ||
    (skill.missing?.config?.length ?? 0) > 0;

  const handleToggle = async () => {
    setToggleLoading(true);
    try {
      await callRpc("skills.update", {
        skillKey: skill.skillKey || skill.name,
        enabled: skill.disabled,
      });
      onRefresh();
    } catch (err) {
      console.error("Failed to toggle skill:", err);
    } finally {
      setToggleLoading(false);
    }
  };

  const handleSaveKey = async () => {
    if (!apiKey.trim()) return;
    setSaveLoading(true);
    setSaveStatus("idle");
    try {
      await callRpc("skills.update", {
        skillKey: skill.skillKey || skill.name,
        apiKey: apiKey.trim(),
      });

      // Persist key in backend for BYOK billing tracking
      const toolId = skill.primaryEnv ? ENV_TO_TOOL_ID[skill.primaryEnv] : null;
      if (toolId) {
        try {
          await api.put(`/settings/keys/${toolId}`, { api_key: apiKey.trim() });
        } catch (err) {
          console.warn("BYOK key persistence failed (non-critical):", err);
        }
      }

      setSaveStatus("success");
      setApiKey("");
      onRefresh();
      setTimeout(() => setSaveStatus("idle"), 3000);
    } catch (err) {
      console.error("Failed to save API key:", err);
      setSaveStatus("error");
      setTimeout(() => setSaveStatus("idle"), 3000);
    } finally {
      setSaveLoading(false);
    }
  };

  const handleInstall = async (spec: SkillInstallSpec) => {
    setInstallLoading(spec.id);
    try {
      await callRpc("skills.install", {
        name: skill.name,
        installId: spec.id,
        timeoutMs: 120000,
      });
      onRefresh();
    } catch (err) {
      console.error("Failed to install:", err);
    } finally {
      setInstallLoading(null);
    }
  };

  return (
    <div className="rounded-lg border border-border p-4 space-y-3 bg-card/30">
      {/* Row 1: Name + Toggle */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            {skill.emoji && <span className="text-base flex-shrink-0">{skill.emoji}</span>}
            <h3 className="text-sm font-medium truncate">{skill.name}</h3>
          </div>
          {skill.description && (
            <p className="text-xs text-muted-foreground mt-1 line-clamp-2">
              {skill.description}
            </p>
          )}
        </div>

        <Button
          variant={skill.disabled ? "outline" : "secondary"}
          size="sm"
          className="flex-shrink-0 text-xs"
          onClick={handleToggle}
          disabled={toggleLoading || skill.always}
        >
          {toggleLoading ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : skill.disabled ? (
            "Enable"
          ) : (
            "Disable"
          )}
        </Button>
      </div>

      {/* Row 2: Badges */}
      <div className="flex items-center gap-1.5 flex-wrap">
        <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-muted text-muted-foreground">
          {SOURCE_LABELS[skill.source] || skill.source}
        </span>
        {skill.eligible ? (
          <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-green-500/10 text-green-500">
            eligible
          </span>
        ) : (
          <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-orange-500/10 text-orange-500">
            blocked
          </span>
        )}
        {skill.disabled && (
          <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-orange-500/10 text-orange-500">
            disabled
          </span>
        )}
      </div>

      {/* Row 3: Missing dependencies */}
      {hasMissing && (
        <div className="space-y-1">
          {(skill.missing?.bins?.length ?? 0) > 0 && (
            <div className="flex items-center gap-1.5 text-xs text-orange-400">
              <AlertTriangle className="h-3 w-3 flex-shrink-0" />
              <span>Missing bin: {skill.missing.bins.join(", ")}</span>
            </div>
          )}
          {(skill.missing?.env?.length ?? 0) > 0 && (
            <div className="flex items-center gap-1.5 text-xs text-orange-400">
              <AlertTriangle className="h-3 w-3 flex-shrink-0" />
              <span>Missing env: {skill.missing.env.join(", ")}</span>
            </div>
          )}
          {(skill.missing?.config?.length ?? 0) > 0 && (
            <div className="flex items-center gap-1.5 text-xs text-orange-400">
              <AlertTriangle className="h-3 w-3 flex-shrink-0" />
              <span>Missing config: {skill.missing.config.join(", ")}</span>
            </div>
          )}
        </div>
      )}

      {/* Row 4: Install buttons */}
      {skill.install?.length > 0 && (skill.missing?.bins?.length ?? 0) > 0 && (
        <div className="flex flex-wrap gap-2">
          {skill.install.map((spec) => (
            <Button
              key={spec.id}
              variant="outline"
              size="sm"
              className="text-xs gap-1.5"
              onClick={() => handleInstall(spec)}
              disabled={installLoading !== null}
            >
              {installLoading === spec.id ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Download className="h-3 w-3" />
              )}
              {spec.label || `Install via ${spec.kind}`}
            </Button>
          ))}
        </div>
      )}

      {/* Row 5: API key input */}
      {skill.primaryEnv && (
        <div className="space-y-1.5">
          <label className="text-xs text-muted-foreground">API key</label>
          <div className="flex gap-2">
            <div className="relative flex-1">
              <Input
                type={apiKeyVisible ? "text" : "password"}
                placeholder={skill.primaryEnv}
                className="h-8 text-xs pr-8 font-mono"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleSaveKey();
                }}
              />
              <button
                type="button"
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                onClick={() => setApiKeyVisible(!apiKeyVisible)}
              >
                {apiKeyVisible ? (
                  <EyeOff className="h-3.5 w-3.5" />
                ) : (
                  <Eye className="h-3.5 w-3.5" />
                )}
              </button>
            </div>
            <Button
              size="sm"
              className="text-xs flex-shrink-0"
              onClick={handleSaveKey}
              disabled={saveLoading || !apiKey.trim()}
            >
              {saveLoading ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : saveStatus === "success" ? (
                "Saved!"
              ) : saveStatus === "error" ? (
                "Failed"
              ) : (
                "Save key"
              )}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
