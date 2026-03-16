"use client";

import { useState, useCallback, useMemo, useEffect } from "react";
import {
  Loader2,
  RefreshCw,
  Bot,
  FileText,
  Wrench,
  Plus,
  User,
  Save,
  AlertCircle,
  FileWarning,
  ToggleLeft,
  ToggleRight,
} from "lucide-react";
import { AgentCreateForm } from "./AgentCreateForm";
import { useGatewayRpc, useGatewayRpcMutation } from "@/hooks/useGatewayRpc";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
type AgentTab = "overview" | "files" | "tools";

interface AgentIdentity {
  name?: string;
  theme?: string;
  emoji?: string;
  avatar?: string;
}

interface AgentEntry {
  id: string;
  name?: string;
  identity?: AgentIdentity;
  model?: string;
}

interface ModelCatalogEntry {
  alias?: string;
}

interface ConfigSnapshot {
  path: string;
  exists: boolean;
  raw: string | null;
  config: ConfigInner;
  hash?: string;
  valid: boolean;
}

interface AgentConfigEntry {
  id: string;
  model?: string | { primary?: string; fallbacks?: string[] };
  [key: string]: unknown;
}

interface ConfigInner {
  agents?: {
    defaults?: {
      models?: Record<string, ModelCatalogEntry>;
      model?: string | { primary?: string };
    };
    list?: AgentConfigEntry[];
  };
  [key: string]: unknown;
}

interface AgentsListResponse {
  defaultId?: string;
  mainKey?: string;
  scope?: string;
  agents?: AgentEntry[];
}

// --- File browser types ---

interface AgentFileEntry {
  name: string;
  path: string;
  missing: boolean;
  size?: number;
  updatedAtMs?: number;
}

interface AgentFilesResponse {
  agentId: string;
  workspace: string;
  files: AgentFileEntry[];
}

interface AgentFileContent {
  agentId: string;
  file: AgentFileEntry & { content?: string };
}

// --- Tools catalog types ---

interface ToolEntry {
  name: string;
  id?: string;
  label?: string;
  description?: string;
  profile?: string;
  category?: string;
  source?: "core" | "plugin";
  pluginId?: string;
  optional?: boolean;
  defaultProfiles?: string[];
  [key: string]: unknown;
}

interface ToolCatalogProfile { id: string; label: string }
interface ToolCatalogGroup { id: string; label: string; source?: "core" | "plugin"; tools: ToolEntry[] }

interface ToolsCatalogResponse {
  agentId?: string;
  profiles?: ToolCatalogProfile[] | Record<string, unknown>;
  groups?: ToolCatalogGroup[];
  tools?: ToolEntry[];
  [key: string]: unknown;
}

// --- Profile policies (determines base tool set per profile) ---

const PROFILE_POLICIES: Record<string, string[]> = {
  minimal: ["session_status"],
  coding: [
    "read", "write", "edit", "apply_patch", "exec", "process",
    "memory_search", "memory_get", "sessions_list", "sessions_history",
    "sessions_send", "sessions_spawn", "subagents", "session_status",
    "cron", "image",
  ],
  messaging: ["sessions_list", "sessions_history", "sessions_send", "session_status", "message"],
  full: [], // empty = all allowed
};

// Tool aliases for normalizing IDs
const TOOL_ALIASES: Record<string, string> = {
  bash: "exec",
  "apply-patch": "apply_patch",
};

// Fallback tool sections if tools.catalog RPC doesn't return groups
const FALLBACK_SECTIONS: { id: string; label: string; tools: { id: string; label: string; description: string; source?: string }[] }[] = [
  { id: "files", label: "Files", tools: [
    { id: "read", label: "read", description: "Read file contents" },
    { id: "write", label: "write", description: "Create or overwrite files" },
    { id: "edit", label: "edit", description: "Edit files with search/replace" },
    { id: "apply_patch", label: "apply_patch", description: "Apply unified diffs" },
  ]},
  { id: "runtime", label: "Runtime", tools: [
    { id: "exec", label: "exec", description: "Run shell commands" },
    { id: "process", label: "process", description: "Manage background processes" },
  ]},
  { id: "web", label: "Web", tools: [
    { id: "web_search", label: "web_search", description: "Search the web" },
    { id: "web_fetch", label: "web_fetch", description: "Fetch web page content" },
  ]},
  { id: "memory", label: "Memory", tools: [
    { id: "memory_search", label: "memory_search", description: "Search agent memory" },
    { id: "memory_get", label: "memory_get", description: "Get memory entries" },
  ]},
  { id: "sessions", label: "Sessions", tools: [
    { id: "sessions_list", label: "sessions_list", description: "List active sessions" },
    { id: "sessions_history", label: "sessions_history", description: "View session history" },
    { id: "sessions_send", label: "sessions_send", description: "Send message to session" },
    { id: "sessions_spawn", label: "sessions_spawn", description: "Spawn new session" },
    { id: "session_status", label: "session_status", description: "Check session status" },
  ]},
  { id: "ui", label: "UI", tools: [
    { id: "image", label: "image", description: "Generate or process images" },
  ]},
  { id: "messaging", label: "Messaging", tools: [
    { id: "message", label: "message", description: "Send messages to channels" },
  ]},
  { id: "automation", label: "Automation", tools: [
    { id: "cron", label: "cron", description: "Schedule recurring tasks" },
  ]},
  { id: "nodes", label: "Nodes", tools: [
    { id: "nodes_list", label: "nodes_list", description: "List compute nodes" },
    { id: "nodes_exec", label: "nodes_exec", description: "Execute on remote nodes" },
  ]},
  { id: "agents", label: "Agents", tools: [
    { id: "subagents", label: "subagents", description: "Spawn and manage sub-agents" },
  ]},
  { id: "media", label: "Media", tools: [
    { id: "audio", label: "audio", description: "Audio processing" },
    { id: "video", label: "video", description: "Video processing" },
  ]},
];

// ---------------------------------------------------------------------------

export function AgentsPanel() {
  const { data: rawData, error, isLoading, mutate } = useGatewayRpc<AgentsListResponse>("agents.list");
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<AgentTab>("overview");
  const [showCreateForm, setShowCreateForm] = useState(false);

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

  // Handle both array and object response formats
  const data = rawData as AgentsListResponse | AgentEntry[] | undefined;
  const agents: AgentEntry[] = Array.isArray(data)
    ? data
    : (data as AgentsListResponse)?.agents ?? [];
  const defaultId = !Array.isArray(data) ? (data as AgentsListResponse)?.defaultId : undefined;

  const current = selectedAgent || agents[0]?.id;

  const TABS: { id: AgentTab; label: string; icon: typeof Bot }[] = [
    { id: "overview", label: "Overview", icon: User },
    { id: "files", label: "Files", icon: FileText },
    { id: "tools", label: "Tools", icon: Wrench },

  ];

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Agents</h2>
          <p className="text-xs text-muted-foreground">{agents.length} configured.</p>
        </div>
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="sm" onClick={() => mutate()}>
            <RefreshCw className="h-3.5 w-3.5" />
          </Button>
          <Button variant="outline" size="sm" onClick={() => setShowCreateForm(true)} disabled={showCreateForm}>
            <Plus className="h-3.5 w-3.5 mr-1" />
            Create Agent
          </Button>
        </div>
      </div>

      {/* Create agent form */}
      {showCreateForm && (
        <AgentCreateForm
          existingIds={agents.map((a) => a.id)}
          onCreated={() => {
            setShowCreateForm(false);
            mutate();
          }}
          onCancel={() => setShowCreateForm(false)}
        />
      )}

      {/* Agent selector */}
      <div className="flex gap-1 flex-wrap">
        {agents.map((a) => (
          <Button
            key={a.id}
            variant={current === a.id ? "default" : "outline"}
            size="sm"
            onClick={() => setSelectedAgent(a.id)}
          >
            {a.identity?.emoji ? (
              <span className="mr-1">{a.identity.emoji}</span>
            ) : (
              <Bot className="h-3.5 w-3.5 mr-1" />
            )}
            {a.identity?.name || a.name || a.id}
            {a.id === defaultId && (
              <span className="ml-1.5 text-[10px] opacity-60">default</span>
            )}
          </Button>
        ))}
      </div>

      {current && (
        <>
          {/* Sub-tabs */}
          <div className="flex gap-1 border-b border-border">
            {TABS.map((tab) => (
              <button
                key={tab.id}
                className={cn(
                  "flex items-center gap-1 px-3 py-1.5 text-xs font-medium transition-colors",
                  activeTab === tab.id
                    ? "text-foreground border-b-2 border-primary"
                    : "text-muted-foreground hover:text-foreground"
                )}
                onClick={() => setActiveTab(tab.id)}
              >
                <tab.icon className="h-3 w-3" />
                {tab.label}
              </button>
            ))}
          </div>

          {/* Tab content */}
          <AgentTabContent agentId={current} agent={agents.find(a => a.id === current)} tab={activeTab} onAgentUpdated={() => mutate()} />
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab router
// ---------------------------------------------------------------------------

function AgentTabContent({ agentId, agent, tab, onAgentUpdated }: { agentId: string; agent?: AgentEntry; tab: AgentTab; onAgentUpdated?: () => void }) {
  if (tab === "overview") {
    return <AgentOverviewTab agentId={agentId} agent={agent} onAgentUpdated={onAgentUpdated} />;
  }
  if (tab === "files") {
    return <AgentFilesTab agentId={agentId} />;
  }
  if (tab === "tools") {
    return <AgentToolsTab agentId={agentId} />;
  }
  return null;
}

// ---------------------------------------------------------------------------
// Overview tab — reads model from config (matching OpenClaw reference pattern)
// ---------------------------------------------------------------------------

/** Resolve the primary model string from a model value (string or {primary, fallbacks}). */
function resolveModelPrimary(model?: string | { primary?: string; fallbacks?: string[] }): string | undefined {
  if (typeof model === "string") return model.trim() || undefined;
  if (typeof model === "object" && model) return model.primary?.trim() || undefined;
  return undefined;
}

function AgentOverviewTab({ agentId, agent, onAgentUpdated }: { agentId: string; agent?: AgentEntry; onAgentUpdated?: () => void }) {
  const { data } = useGatewayRpc<Record<string, unknown>>(
    "agent.identity.get",
    { agentId },
  );
  const { data: configSnapshot, mutate: mutateConfig } = useGatewayRpc<ConfigSnapshot>("config.get");
  const callRpc = useGatewayRpcMutation();
  const [updatingModel, setUpdatingModel] = useState(false);
  const [modelError, setModelError] = useState<string | null>(null);

  const identity = data || agent?.identity;

  // config.get returns a ConfigSnapshot wrapper; actual config is under .config
  const configInner = configSnapshot?.config;

  // Model catalog: agents.defaults.models (dict of modelId -> { alias? })
  const modelsCatalog = configInner?.agents?.defaults?.models ?? {};

  // Default model: agents.defaults.model (string or { primary })
  const defaultModelPrimary = resolveModelPrimary(configInner?.agents?.defaults?.model);

  // Per-agent model: agents.list[].model where id matches (reference pattern)
  const agentConfigEntry = configInner?.agents?.list?.find(a => a?.id === agentId);
  const agentModelPrimary = resolveModelPrimary(agentConfigEntry?.model);

  // Effective model: per-agent overrides default
  const currentModel = agentModelPrimary || defaultModelPrimary || "";

  // Save model via agents.update RPC (purpose-built for updating agent properties).
  // We avoid config.set because config.get redacts sensitive values (channel tokens etc.)
  // — sending redacted config back would corrupt the config file.
  const handleModelChange = useCallback(async (newModel: string) => {
    setUpdatingModel(true);
    setModelError(null);
    try {
      // Empty string = clear per-agent override → inherit default
      await callRpc("agents.update", {
        agentId,
        ...(newModel ? { model: newModel } : { model: null }),
      });

      // Refresh config and agent list after save
      mutateConfig();
      onAgentUpdated?.();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      console.error("Failed to update model:", msg);
      setModelError(msg);
    } finally {
      setUpdatingModel(false);
    }
  }, [callRpc, agentId, onAgentUpdated, mutateConfig]);

  // Build options list — catalog models + current model if not in catalog
  const modelOptions: { id: string; label: string }[] = Object.entries(modelsCatalog).map(
    ([id, entry]) => ({ id, label: entry.alias || id.split("/").pop() || id })
  );
  if (currentModel && !modelsCatalog[currentModel]) {
    modelOptions.unshift({ id: currentModel, label: `Current (${currentModel.split("/").pop()})` });
  }

  // Is this the default agent? (no per-agent override = inherits default)
  const isDefault = !agentModelPrimary;

  return (
    <div className="space-y-4 mt-2">
      <div className="rounded-lg border border-border p-4 space-y-3">
        <h3 className="text-sm font-medium">Identity</h3>
        <div className="grid grid-cols-2 gap-3">
          <InfoRow label="Agent ID" value={agentId} />
          <InfoRow label="Name" value={(identity as Record<string, unknown>)?.name as string || agent?.name || "\u2014"} />
          <InfoRow label="Emoji" value={(identity as Record<string, unknown>)?.emoji as string || "\u2014"} />
          <InfoRow label="Theme" value={(identity as Record<string, unknown>)?.theme as string || "\u2014"} />
        </div>
      </div>

      {/* Model selector */}
      <div className="rounded-lg border border-border p-4 space-y-3">
        <h3 className="text-sm font-medium">Model</h3>
        {modelOptions.length > 0 || defaultModelPrimary ? (
          <select
            className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
            value={isDefault ? "" : currentModel}
            onChange={(e) => handleModelChange(e.target.value)}
            disabled={updatingModel || !configSnapshot?.hash}
          >
            {!isDefault && (
              <option value="">
                {defaultModelPrimary
                  ? `Inherit default (${defaultModelPrimary.split("/").pop()})`
                  : "Inherit default"}
              </option>
            )}
            {modelOptions.map((opt) => (
              <option key={opt.id} value={opt.id}>
                {opt.label}{opt.id === defaultModelPrimary ? " (default)" : ""}
              </option>
            ))}
          </select>
        ) : (
          <p className="text-xs text-muted-foreground">
            {currentModel ? currentModel.split("/").pop() : "No models configured in gateway"}
          </p>
        )}
        {updatingModel && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
        {modelError && (
          <p className="text-xs text-destructive flex items-center gap-1">
            <AlertCircle className="h-3 w-3" /> {modelError}
          </p>
        )}
      </div>

      {/* Raw data */}
      {data && (
        <details className="group">
          <summary className="text-xs text-muted-foreground/60 cursor-pointer hover:text-muted-foreground">
            Raw identity data
          </summary>
          <pre className="mt-2 text-xs bg-muted/30 rounded-lg p-3 overflow-auto max-h-48">
            {JSON.stringify(data, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Files tab — agents.files.list / get / set
// ---------------------------------------------------------------------------

const KNOWN_FILES = [
  "SOUL.md", "MEMORY.md", "TOOLS.md", "IDENTITY.md",
  "USER.md", "HEARTBEAT.md", "BOOTSTRAP.md", "AGENTS.md",
];

function AgentFilesTab({ agentId }: { agentId: string }) {
  const { data, error, isLoading, mutate } = useGatewayRpc<AgentFilesResponse>(
    "agents.files.list",
    { agentId },
  );
  const callRpc = useGatewayRpcMutation();
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState<string>("");
  const [loadingFile, setLoadingFile] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);

  const files = data?.files ?? [];

  const handleFileClick = useCallback(async (name: string) => {
    setSelectedFile(name);
    setLoadingFile(true);
    setSaveError(null);
    setDirty(false);
    try {
      const res = await callRpc<AgentFileContent>("agents.files.get", { agentId, name });
      setFileContent(res.file?.content ?? "");
    } catch (err) {
      setFileContent("");
      setSaveError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoadingFile(false);
    }
  }, [callRpc, agentId]);

  const handleSave = useCallback(async () => {
    if (!selectedFile) return;
    setSaving(true);
    setSaveError(null);
    try {
      await callRpc("agents.files.set", { agentId, name: selectedFile, content: fileContent });
      setDirty(false);
      mutate();
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }, [callRpc, agentId, selectedFile, fileContent, mutate]);

  if (isLoading) {
    return <Loader2 className="h-4 w-4 animate-spin text-muted-foreground mt-4" />;
  }

  if (error) {
    return (
      <div className="mt-4 space-y-2">
        <p className="text-sm text-destructive">{error.message}</p>
        <Button variant="outline" size="sm" onClick={() => mutate()}>
          <RefreshCw className="h-3.5 w-3.5 mr-1.5" /> Retry
        </Button>
      </div>
    );
  }

  // Merge gateway response with known files list
  const fileMap = new Map(files.map((f) => [f.name, f]));
  const allFiles: AgentFileEntry[] = KNOWN_FILES.map((name) => {
    const existing = fileMap.get(name);
    return existing ?? { name, path: name, missing: true };
  });
  // Add any extra files from gateway not in our known list
  for (const f of files) {
    if (!KNOWN_FILES.includes(f.name)) {
      allFiles.push(f);
    }
  }

  return (
    <div className="mt-2 space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">{allFiles.length} files</p>
        <Button variant="ghost" size="sm" onClick={() => mutate()}>
          <RefreshCw className="h-3.5 w-3.5" />
        </Button>
      </div>

      {/* File list */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-1">
        {allFiles.map((f) => (
          <button
            key={f.name}
            className={cn(
              "flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs text-left transition-colors",
              selectedFile === f.name
                ? "bg-primary/10 text-primary border border-primary/30"
                : "hover:bg-muted/50",
              f.missing && "opacity-50",
            )}
            onClick={() => handleFileClick(f.name)}
          >
            {f.missing ? (
              <FileWarning className="h-3 w-3 flex-shrink-0 text-muted-foreground" />
            ) : (
              <FileText className="h-3 w-3 flex-shrink-0" />
            )}
            <span className="truncate">{f.name}</span>
            {f.size != null && !f.missing && (
              <span className="text-[10px] text-muted-foreground/50 ml-auto flex-shrink-0">
                {f.size > 1024 ? `${(f.size / 1024).toFixed(1)}k` : `${f.size}b`}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* File editor */}
      {selectedFile && (
        <div className="rounded-lg border border-border overflow-hidden">
          <div className="flex items-center justify-between px-3 py-2 bg-muted/20 border-b border-border">
            <span className="text-xs font-medium">{selectedFile}</span>
            <div className="flex items-center gap-2">
              {dirty && <span className="text-[10px] text-yellow-500">unsaved</span>}
              <Button
                variant="default"
                size="sm"
                onClick={handleSave}
                disabled={saving || !dirty}
              >
                {saving ? (
                  <Loader2 className="h-3 w-3 animate-spin mr-1" />
                ) : (
                  <Save className="h-3 w-3 mr-1" />
                )}
                Save
              </Button>
            </div>
          </div>

          {saveError && (
            <div className="flex items-center gap-2 px-3 py-2 bg-destructive/5 border-b border-destructive/20">
              <AlertCircle className="h-3 w-3 text-destructive flex-shrink-0" />
              <span className="text-xs text-destructive">{saveError}</span>
            </div>
          )}

          {loadingFile ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <textarea
              className="w-full min-h-[300px] p-3 text-xs font-mono bg-background resize-y focus:outline-none"
              value={fileContent}
              onChange={(e) => {
                setFileContent(e.target.value);
                setDirty(true);
              }}
              spellCheck={false}
            />
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tools tab — tools.catalog
// ---------------------------------------------------------------------------

/** Normalize a tool ID through aliases */
function normalizeToolId(id: string): string {
  return TOOL_ALIASES[id] ?? id;
}

/** Check if a tool is allowed given profile policy + alsoAllow/deny */
function isToolAllowed(
  toolId: string,
  profileId: string,
  alsoAllow: string[],
  deny: string[],
): boolean {
  const normalized = normalizeToolId(toolId);
  if (deny.includes(normalized)) return false;
  const basePolicy = PROFILE_POLICIES[profileId];
  if (!basePolicy) return true; // unknown profile → allow all
  // "full" profile has empty policy → all allowed
  if (basePolicy.length === 0) return true;
  return basePolicy.includes(normalized) || alsoAllow.includes(normalized);
}

function AgentToolsTab({ agentId }: { agentId: string }) {
  const { data: catalogData, error: catalogError, isLoading: catalogLoading, mutate: mutateCatalog } =
    useGatewayRpc<ToolsCatalogResponse>("tools.catalog", { agentId, includePlugins: true });
  const { data: configSnapshot, mutate: mutateConfig } =
    useGatewayRpc<ConfigSnapshot>("config.get");
  const callRpc = useGatewayRpcMutation();

  // Local state for editing
  const [localProfile, setLocalProfile] = useState<string | null>(null);
  const [localAlsoAllow, setLocalAlsoAllow] = useState<string[]>([]);
  const [localDeny, setLocalDeny] = useState<string[]>([]);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Extract agent tools config from config.get
  const configInner = configSnapshot?.config;
  const agentConfigEntry = configInner?.agents?.list?.find(
    (a: AgentConfigEntry) => a?.id === agentId,
  );
  const agentToolsConfig = agentConfigEntry?.tools as
    | { profile?: string; alsoAllow?: string[]; deny?: string[] }
    | undefined;
  const globalToolsConfig = configInner?.tools as
    | { profile?: string; allow?: string[] }
    | undefined;

  // Resolve effective profile: agent override > global > "full"
  const serverProfile = agentToolsConfig?.profile ?? globalToolsConfig?.profile ?? "full";
  const serverAlsoAllow = agentToolsConfig?.alsoAllow ?? [];
  const serverDeny = agentToolsConfig?.deny ?? [];

  // Initialize local state from server on first load / after save
  useEffect(() => {
    if (!dirty) {
      setLocalProfile(agentToolsConfig?.profile ?? null);
      setLocalAlsoAllow([...serverAlsoAllow]);
      setLocalDeny([...serverDeny]);
    }
  }, [agentToolsConfig?.profile, dirty]); // eslint-disable-line react-hooks/exhaustive-deps

  // Effective profile for display
  const effectiveProfile = localProfile ?? globalToolsConfig?.profile ?? "full";
  const profileSource = localProfile ? "agent" : globalToolsConfig?.profile ? "global" : "default";

  // Build sections from catalog or fallback
  const sections = useMemo(() => {
    if (catalogData?.groups && catalogData.groups.length > 0) {
      return catalogData.groups.map((g) => ({
        id: g.id,
        label: g.label,
        source: g.source,
        tools: g.tools.map((t) => ({
          id: normalizeToolId(t.id ?? t.name),
          label: t.label ?? t.name,
          description: t.description ?? "",
          source: t.source,
        })),
      }));
    }
    // Fallback: use catalogData.tools grouped, or hardcoded sections
    if (catalogData?.tools && catalogData.tools.length > 0) {
      const grouped = new Map<string, { id: string; label: string; description: string; source?: string }[]>();
      for (const tool of catalogData.tools) {
        const group = tool.profile || tool.category || "default";
        const list = grouped.get(group) ?? [];
        list.push({
          id: normalizeToolId(tool.id ?? tool.name),
          label: tool.label ?? tool.name,
          description: tool.description ?? "",
          source: tool.source,
        });
        grouped.set(group, list);
      }
      return Array.from(grouped.entries()).map(([key, tools]) => ({
        id: key,
        label: key.charAt(0).toUpperCase() + key.slice(1),
        tools,
      }));
    }
    return FALLBACK_SECTIONS;
  }, [catalogData]);

  // All tool IDs for counting
  const allToolIds = useMemo(
    () => sections.flatMap((s) => s.tools.map((t) => t.id)),
    [sections],
  );
  const totalTools = allToolIds.length;
  const enabledCount = allToolIds.filter((id) =>
    isToolAllowed(id, effectiveProfile, localAlsoAllow, localDeny),
  ).length;

  // Toggle a single tool
  const toggleTool = useCallback(
    (toolId: string) => {
      const normalized = normalizeToolId(toolId);
      const currentlyAllowed = isToolAllowed(normalized, effectiveProfile, localAlsoAllow, localDeny);

      if (currentlyAllowed) {
        // Disable: remove from alsoAllow, add to deny
        setLocalAlsoAllow((prev) => prev.filter((id) => id !== normalized));
        setLocalDeny((prev) => (prev.includes(normalized) ? prev : [...prev, normalized]));
      } else {
        // Enable: remove from deny; if not in base profile, add to alsoAllow
        setLocalDeny((prev) => prev.filter((id) => id !== normalized));
        const basePolicy = PROFILE_POLICIES[effectiveProfile] ?? [];
        if (basePolicy.length > 0 && !basePolicy.includes(normalized)) {
          setLocalAlsoAllow((prev) => (prev.includes(normalized) ? prev : [...prev, normalized]));
        }
      }
      setDirty(true);
    },
    [effectiveProfile, localAlsoAllow, localDeny],
  );

  // Enable / Disable all
  const enableAll = useCallback(() => {
    setLocalAlsoAllow([...allToolIds]);
    setLocalDeny([]);
    setDirty(true);
  }, [allToolIds]);

  const disableAll = useCallback(() => {
    setLocalAlsoAllow([]);
    setLocalDeny([...allToolIds]);
    setDirty(true);
  }, [allToolIds]);

  // Profile preset
  const applyPreset = useCallback(
    (preset: string | null) => {
      if (preset === null) {
        // Inherit: clear agent override
        setLocalProfile(null);
      } else {
        setLocalProfile(preset);
      }
      setLocalAlsoAllow([]);
      setLocalDeny([]);
      setDirty(true);
    },
    [],
  );

  // Reload from server
  const handleReload = useCallback(() => {
    setDirty(false);
    setSaveError(null);
    mutateCatalog();
    mutateConfig();
  }, [mutateCatalog, mutateConfig]);

  // Save via agents.update
  const handleSave = useCallback(async () => {
    setSaving(true);
    setSaveError(null);
    try {
      const toolsPayload: Record<string, unknown> = {};
      if (localProfile !== null) {
        toolsPayload.profile = localProfile;
      }
      if (localAlsoAllow.length > 0) {
        toolsPayload.alsoAllow = localAlsoAllow;
      }
      if (localDeny.length > 0) {
        toolsPayload.deny = localDeny;
      }
      await callRpc("agents.update", { agentId, tools: toolsPayload });
      setDirty(false);
      mutateConfig();
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }, [callRpc, agentId, localProfile, localAlsoAllow, localDeny, mutateConfig]);

  if (catalogLoading) {
    return <Loader2 className="h-4 w-4 animate-spin text-muted-foreground mt-4" />;
  }

  if (catalogError) {
    return (
      <div className="mt-4 space-y-2">
        <p className="text-sm text-destructive">{catalogError.message}</p>
        <Button variant="outline" size="sm" onClick={() => mutateCatalog()}>
          <RefreshCw className="h-3.5 w-3.5 mr-1.5" /> Retry
        </Button>
      </div>
    );
  }

  const presets = [
    { id: "minimal", label: "Minimal" },
    { id: "coding", label: "Coding" },
    { id: "messaging", label: "Messaging" },
    { id: "full", label: "Full" },
  ];

  return (
    <div className="mt-2 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-medium">Tool Access</h3>
          <p className="text-xs text-muted-foreground">
            {enabledCount}/{totalTools} enabled
          </p>
        </div>
        <div className="flex items-center gap-1">
          <Button variant="outline" size="sm" onClick={enableAll}>
            Enable All
          </Button>
          <Button variant="outline" size="sm" onClick={disableAll}>
            Disable All
          </Button>
          <Button variant="ghost" size="sm" onClick={handleReload}>
            <RefreshCw className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="default"
            size="sm"
            onClick={handleSave}
            disabled={saving || !dirty}
          >
            {saving ? (
              <Loader2 className="h-3 w-3 animate-spin mr-1" />
            ) : (
              <Save className="h-3 w-3 mr-1" />
            )}
            Save
          </Button>
        </div>
      </div>

      {saveError && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-md bg-destructive/5 border border-destructive/20">
          <AlertCircle className="h-3 w-3 text-destructive flex-shrink-0" />
          <span className="text-xs text-destructive">{saveError}</span>
        </div>
      )}

      {/* Global allow warning */}
      {globalToolsConfig?.allow && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-md bg-yellow-500/5 border border-yellow-500/20">
          <AlertCircle className="h-3 w-3 text-yellow-600 flex-shrink-0" />
          <span className="text-xs text-yellow-700">
            Global <code className="text-[10px] bg-muted/50 px-1 rounded">tools.allow</code> is set — this may restrict available tools regardless of agent config.
          </span>
        </div>
      )}

      {/* Profile info */}
      <div className="flex items-center gap-3 text-xs text-muted-foreground">
        <span>
          Profile: <span className="font-medium text-foreground">{effectiveProfile}</span>
        </span>
        <span>
          Source: <span className="font-medium text-foreground">{profileSource}</span>
        </span>
        {dirty && (
          <span className="text-yellow-500 font-medium">unsaved</span>
        )}
      </div>

      {/* Quick presets */}
      <div className="flex items-center gap-1 flex-wrap">
        <span className="text-xs text-muted-foreground mr-1">Quick Presets:</span>
        {presets.map((preset) => (
          <Button
            key={preset.id}
            variant={effectiveProfile === preset.id && localProfile === preset.id ? "default" : "outline"}
            size="sm"
            className="h-6 text-xs px-2"
            onClick={() => applyPreset(preset.id)}
          >
            {preset.label}
          </Button>
        ))}
        <Button
          variant={localProfile === null ? "default" : "outline"}
          size="sm"
          className="h-6 text-xs px-2"
          onClick={() => applyPreset(null)}
        >
          Inherit
        </Button>
      </div>

      {/* Tool sections with toggles */}
      {sections.map((section) => (
        <div key={section.id} className="space-y-1">
          <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
            {section.label}
          </h4>
          <div className="space-y-0.5">
            {section.tools.map((tool) => {
              const allowed = isToolAllowed(tool.id, effectiveProfile, localAlsoAllow, localDeny);
              return (
                <div
                  key={tool.id}
                  className="flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-accent/50 group"
                >
                  <button
                    className="flex-shrink-0 focus:outline-none"
                    onClick={() => toggleTool(tool.id)}
                    aria-label={`Toggle ${tool.label}`}
                  >
                    {allowed ? (
                      <ToggleRight className="h-4 w-4 text-primary" />
                    ) : (
                      <ToggleLeft className="h-4 w-4 text-muted-foreground/40" />
                    )}
                  </button>
                  <div className="min-w-0 flex-1">
                    <div className={cn(
                      "text-sm font-medium truncate",
                      !allowed && "text-muted-foreground/50",
                    )}>
                      {tool.label}
                    </div>
                    {tool.description && (
                      <div className="text-xs text-muted-foreground/70 line-clamp-1">
                        {tool.description}
                      </div>
                    )}
                  </div>
                  {tool.source && (
                    <span className="text-[10px] text-muted-foreground/40 flex-shrink-0">
                      {String(tool.source)}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      ))}

      {/* Raw data */}
      <details className="group">
        <summary className="text-xs text-muted-foreground/60 cursor-pointer hover:text-muted-foreground">
          Raw catalog data
        </summary>
        <pre className="mt-2 text-xs bg-muted/30 rounded-lg p-3 overflow-auto max-h-48">
          {JSON.stringify(catalogData, null, 2)}
        </pre>
      </details>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared components
// ---------------------------------------------------------------------------

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground/60">{label}</div>
      <div className="text-sm font-medium truncate">{value}</div>
    </div>
  );
}
