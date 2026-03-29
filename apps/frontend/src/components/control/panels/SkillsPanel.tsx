"use client";

import { useState } from "react";
import {
  Loader2,
  RefreshCw,
  Search,
  AlertTriangle,
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

// --- Grouping (kept for internal use) ---

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

// --- Category mapping ---

type Category = "All" | "Installed" | "Communication" | "Productivity" | "Research" | "Developer";

const CATEGORIES: Category[] = ["All", "Installed", "Communication", "Productivity", "Research", "Developer"];

const SKILL_CATEGORY_MAP: Record<string, Category> = {
  // Communication
  message: "Communication",
  email: "Communication",
  slack: "Communication",
  discord: "Communication",
  telegram: "Communication",
  whatsapp: "Communication",
  notify: "Communication",
  chat: "Communication",
  sms: "Communication",
  // Productivity
  calendar: "Productivity",
  schedule: "Productivity",
  task: "Productivity",
  todo: "Productivity",
  notes: "Productivity",
  memory: "Productivity",
  file: "Productivity",
  spreadsheet: "Productivity",
  google: "Productivity",
  notion: "Productivity",
  // Research
  search: "Research",
  browse: "Research",
  web: "Research",
  perplexity: "Research",
  firecrawl: "Research",
  scrape: "Research",
  crawl: "Research",
  wikipedia: "Research",
  arxiv: "Research",
  news: "Research",
};

function getSkillCategory(skill: SkillStatusEntry): Category {
  const nameLower = skill.name.toLowerCase();
  for (const [keyword, category] of Object.entries(SKILL_CATEGORY_MAP)) {
    if (nameLower.includes(keyword)) return category;
  }
  const descLower = (skill.description || "").toLowerCase();
  for (const [keyword, category] of Object.entries(SKILL_CATEGORY_MAP)) {
    if (descLower.includes(keyword)) return category;
  }
  return "Developer";
}

// --- Friendly descriptions for known skills ---

const FRIENDLY_DESCRIPTIONS: Record<string, string> = {
  perplexity: "Search the web with AI-powered answers and citations",
  firecrawl: "Scrape and crawl websites to extract structured data",
  elevenlabs: "Generate natural-sounding speech from text",
  memory: "Remember facts and context across conversations",
  computercontroller: "Control your computer with mouse and keyboard",
  developer: "Write, run, and debug code in your workspace",
  codesearch: "Search and navigate your codebase intelligently",
  webpilot: "Browse and interact with web pages",
  calendar: "Manage events and schedules",
};

function getFriendlyDescription(skill: SkillStatusEntry): string {
  const key = skill.name.toLowerCase().replace(/[^a-z0-9]/g, "");
  return FRIENDLY_DESCRIPTIONS[key] || skill.description || "Extend your agent's capabilities";
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
      <div className="flex border-b border-[#e0dbd0] px-2">
        {TABS.map((tab) => {
          const Icon = tab.icon;
          return (
            <button
              key={tab.id}
              className={cn(
                "flex items-center gap-1.5 px-3 py-2 text-xs font-medium transition-colors border-b-2 -mb-px",
                activeTab === tab.id
                  ? "border-[#2d8a4e] text-[#1a1a1a]"
                  : "border-transparent text-[#8a8578] hover:text-[#1a1a1a]",
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

// --- Skills Tab ---

function SkillsTab({ agentId }: { agentId?: string }) {
  const params = agentId ? { agentId } : {};
  const { data: raw, error, isLoading, mutate } = useGatewayRpc<SkillStatusReport | SkillStatusEntry[]>(
    "skills.status",
    params,
  );
  const callRpc = useGatewayRpcMutation();
  const api = useApi();
  const [filter, setFilter] = useState("");
  const [activeCategory, setActiveCategory] = useState<Category>("All");

  // Normalize response: could be SkillStatusReport or raw array
  const skills: SkillStatusEntry[] = Array.isArray(raw) ? raw : raw?.skills ?? [];

  // Apply search filter
  const searchFiltered = filter
    ? skills.filter(
        (s) =>
          s.name.toLowerCase().includes(filter.toLowerCase()) ||
          s.description?.toLowerCase().includes(filter.toLowerCase()),
      )
    : skills;

  // Apply category filter
  const filtered = searchFiltered.filter((s) => {
    if (activeCategory === "All") return true;
    if (activeCategory === "Installed") return !s.disabled;
    return getSkillCategory(s) === activeCategory;
  });

  const installedSkills = filtered.filter((s) => !s.disabled);
  const availableSkills = filtered.filter((s) => s.disabled);

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center py-20">
        <Loader2 className="h-5 w-5 animate-spin text-[#8a8578]" />
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
    <div className="bg-[#faf7f2] min-h-full">
      <div className="p-6 space-y-5">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-semibold" style={{ fontFamily: "'Lora', serif" }}>
              Skill Store
            </h2>
            <p className="text-sm text-[#8a8578] mt-0.5" style={{ fontFamily: "'DM Sans', sans-serif" }}>
              Discover and install skills for your agent
            </p>
          </div>
          <Button variant="ghost" size="sm" onClick={() => mutate()} className="text-[#8a8578] hover:text-[#1a1a1a]">
            <RefreshCw className="h-3.5 w-3.5" />
          </Button>
        </div>

        {/* Search bar */}
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[#8a8578]" />
          <Input
            placeholder="Search skills..."
            className="pl-10 h-10 text-sm bg-white border-[#e0dbd0] rounded-lg"
            style={{ fontFamily: "'DM Sans', sans-serif" }}
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        </div>

        {/* Category pills */}
        <div className="flex items-center gap-2 overflow-x-auto pb-1">
          {CATEGORIES.map((cat) => (
            <button
              key={cat}
              onClick={() => setActiveCategory(cat)}
              className={cn(
                "px-3.5 py-1.5 rounded-full text-xs font-medium whitespace-nowrap transition-colors border",
                activeCategory === cat
                  ? "bg-[#06402B] text-white border-[#06402B]"
                  : "bg-white text-[#5a5549] border-[#e0dbd0] hover:border-[#c5c0b6]",
              )}
              style={{ fontFamily: "'DM Sans', sans-serif" }}
            >
              {cat}
              {cat === "Installed" && ` (${skills.filter((s) => !s.disabled).length})`}
            </button>
          ))}
        </div>

        {/* No results */}
        {filtered.length === 0 && (
          <p className="text-sm text-[#8a8578] text-center py-8" style={{ fontFamily: "'DM Sans', sans-serif" }}>
            No skills found.
          </p>
        )}

        {/* Installed skills section */}
        {installedSkills.length > 0 && activeCategory !== "Installed" && (
          <div className="space-y-3">
            <h3
              className="text-sm font-semibold text-[#1a1a1a] tracking-wide"
              style={{ fontFamily: "'Lora', serif" }}
            >
              Installed
            </h3>
            <div className="grid gap-3">
              {installedSkills.map((skill) => (
                <SkillCard
                  key={skill.skillKey || skill.name}
                  skill={skill}
                  callRpc={callRpc}
                  api={api}
                  onRefresh={mutate}
                  variant="installed"
                />
              ))}
            </div>
          </div>
        )}

        {/* When on Installed category, show all installed in one section */}
        {activeCategory === "Installed" && installedSkills.length > 0 && (
          <div className="grid gap-3">
            {installedSkills.map((skill) => (
              <SkillCard
                key={skill.skillKey || skill.name}
                skill={skill}
                callRpc={callRpc}
                api={api}
                onRefresh={mutate}
                variant="installed"
              />
            ))}
          </div>
        )}

        {/* Available skills section */}
        {availableSkills.length > 0 && activeCategory !== "Installed" && (
          <div className="space-y-3">
            <h3
              className="text-sm font-semibold text-[#1a1a1a] tracking-wide"
              style={{ fontFamily: "'Lora', serif" }}
            >
              Available
            </h3>
            <div className="grid gap-3">
              {availableSkills.map((skill) => (
                <SkillCard
                  key={skill.skillKey || skill.name}
                  skill={skill}
                  callRpc={callRpc}
                  api={api}
                  onRefresh={mutate}
                  variant="available"
                />
              ))}
            </div>
          </div>
        )}

        {/* Bottom link */}
        <div className="pt-2 pb-4 text-center">
          <a
            href="https://clawhub.ai/skills?sort=downloads&nonSuspicious=true"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 text-sm text-[#2d8a4e] hover:text-[#06402B] transition-colors"
            style={{ fontFamily: "'DM Sans', sans-serif" }}
          >
            Need more? Browse all skills on ClawHub
            <ExternalLink className="h-3.5 w-3.5" />
          </a>
        </div>
      </div>
    </div>
  );
}

// --- Skill Card ---

function SkillCard({
  skill,
  callRpc,
  api,
  onRefresh,
  variant,
}: {
  skill: SkillStatusEntry;
  callRpc: <T = unknown>(method: string, params?: Record<string, unknown>) => Promise<T>;
  api: ReturnType<typeof useApi>;
  onRefresh: () => void;
  variant: "installed" | "available";
}) {
  const [toggleLoading, setToggleLoading] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [apiKeyVisible, setApiKeyVisible] = useState(false);
  const [saveLoading, setSaveLoading] = useState(false);
  const [saveStatus, setSaveStatus] = useState<"idle" | "success" | "error">("idle");
  const [installLoading, setInstallLoading] = useState<string | null>(null);
  const [configExpanded, setConfigExpanded] = useState(false);

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

  const friendlyDesc = getFriendlyDescription(skill);

  if (variant === "installed") {
    return (
      <div className="rounded-xl border border-[#e0dbd0] bg-white p-4 space-y-3">
        {/* Top row: icon + info + badge + actions */}
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-3 min-w-0 flex-1">
            <span className="text-2xl flex-shrink-0 mt-0.5">{skill.emoji || "🧩"}</span>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <h3
                  className="text-sm font-semibold text-[#1a1a1a] truncate"
                  style={{ fontFamily: "'DM Sans', sans-serif" }}
                >
                  {skill.name}
                </h3>
                <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-[#e8f5e9] text-[#2d8a4e] flex-shrink-0">
                  Installed
                </span>
              </div>
              <p
                className="text-xs text-[#8a8578] mt-0.5 line-clamp-2"
                style={{ fontFamily: "'DM Sans', sans-serif" }}
              >
                {friendlyDesc}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 flex-shrink-0">
            {skill.primaryEnv && (
              <button
                onClick={() => setConfigExpanded(!configExpanded)}
                className={cn(
                  "px-3 py-1.5 rounded-lg text-xs font-medium transition-colors border",
                  configExpanded
                    ? "bg-[#f3efe6] border-[#d5d0c7] text-[#1a1a1a]"
                    : "bg-white border-[#e0dbd0] text-[#5a5549] hover:border-[#c5c0b6]",
                )}
                style={{ fontFamily: "'DM Sans', sans-serif" }}
              >
                Configure
              </button>
            )}
            {!skill.always && (
              <button
                onClick={handleToggle}
                disabled={toggleLoading}
                className="px-3 py-1.5 rounded-lg text-xs font-medium border border-[#e0dbd0] text-[#8a8578] hover:text-[#1a1a1a] hover:border-[#c5c0b6] transition-colors"
                style={{ fontFamily: "'DM Sans', sans-serif" }}
              >
                {toggleLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : "Disable"}
              </button>
            )}
          </div>
        </div>

        {/* Missing dependencies */}
        {hasMissing && (
          <div className="space-y-1">
            {(skill.missing?.bins?.length ?? 0) > 0 && (
              <div className="flex items-center gap-1.5 text-xs text-orange-500">
                <AlertTriangle className="h-3 w-3 flex-shrink-0" />
                <span>Missing: {skill.missing.bins.join(", ")}</span>
              </div>
            )}
            {(skill.missing?.env?.length ?? 0) > 0 && (
              <div className="flex items-center gap-1.5 text-xs text-orange-500">
                <AlertTriangle className="h-3 w-3 flex-shrink-0" />
                <span>Missing env: {skill.missing.env.join(", ")}</span>
              </div>
            )}
            {(skill.missing?.config?.length ?? 0) > 0 && (
              <div className="flex items-center gap-1.5 text-xs text-orange-500">
                <AlertTriangle className="h-3 w-3 flex-shrink-0" />
                <span>Missing config: {skill.missing.config.join(", ")}</span>
              </div>
            )}
          </div>
        )}

        {/* Install buttons for missing bins */}
        {skill.install?.length > 0 && (skill.missing?.bins?.length ?? 0) > 0 && (
          <div className="flex flex-wrap gap-2">
            {skill.install.map((spec) => (
              <Button
                key={spec.id}
                variant="outline"
                size="sm"
                className="text-xs gap-1.5 rounded-lg"
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

        {/* Expandable configure panel with API key */}
        {configExpanded && skill.primaryEnv && (
          <div className="border-t border-[#e0dbd0] pt-3 space-y-2">
            <label
              className="text-xs font-medium text-[#5a5549]"
              style={{ fontFamily: "'DM Sans', sans-serif" }}
            >
              API Key ({skill.primaryEnv})
            </label>
            <div className="flex gap-2">
              <div className="relative flex-1">
                <Input
                  type={apiKeyVisible ? "text" : "password"}
                  placeholder={`Enter your ${skill.primaryEnv}`}
                  className="h-9 text-xs pr-8 font-mono bg-[#faf7f2] border-[#e0dbd0] rounded-lg"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") handleSaveKey();
                  }}
                />
                <button
                  type="button"
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[#8a8578] hover:text-[#1a1a1a]"
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
                className="text-xs flex-shrink-0 rounded-lg bg-[#06402B] hover:bg-[#053d28] text-white"
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
                  "Save"
                )}
              </Button>
            </div>
          </div>
        )}
      </div>
    );
  }

  // --- Available (disabled) skill card ---
  return (
    <div className="rounded-xl border border-[#e0dbd0] bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3 min-w-0 flex-1">
          <span className="text-2xl flex-shrink-0 mt-0.5">{skill.emoji || "🧩"}</span>
          <div className="min-w-0 flex-1">
            <h3
              className="text-sm font-semibold text-[#1a1a1a] truncate"
              style={{ fontFamily: "'DM Sans', sans-serif" }}
            >
              {skill.name}
            </h3>
            <p
              className="text-xs text-[#8a8578] mt-0.5 line-clamp-2"
              style={{ fontFamily: "'DM Sans', sans-serif" }}
            >
              {friendlyDesc}
            </p>

            {/* Missing dependencies inline */}
            {hasMissing && (
              <div className="mt-2 space-y-0.5">
                {(skill.missing?.bins?.length ?? 0) > 0 && (
                  <div className="flex items-center gap-1 text-[11px] text-orange-500">
                    <AlertTriangle className="h-2.5 w-2.5 flex-shrink-0" />
                    <span>Needs: {skill.missing.bins.join(", ")}</span>
                  </div>
                )}
                {(skill.missing?.env?.length ?? 0) > 0 && (
                  <div className="flex items-center gap-1 text-[11px] text-orange-500">
                    <AlertTriangle className="h-2.5 w-2.5 flex-shrink-0" />
                    <span>Needs env: {skill.missing.env.join(", ")}</span>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2 flex-shrink-0">
          {/* Install dependency buttons */}
          {skill.install?.length > 0 && (skill.missing?.bins?.length ?? 0) > 0 && (
            <>
              {skill.install.map((spec) => (
                <button
                  key={spec.id}
                  onClick={() => handleInstall(spec)}
                  disabled={installLoading !== null}
                  className="px-3 py-1.5 rounded-full text-xs font-medium border border-[#e0dbd0] text-[#5a5549] hover:border-[#c5c0b6] transition-colors"
                  style={{ fontFamily: "'DM Sans', sans-serif" }}
                >
                  {installLoading === spec.id ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <>{spec.label || `Install ${spec.kind}`}</>
                  )}
                </button>
              ))}
            </>
          )}

          {/* Install / Enable button */}
          <button
            onClick={handleToggle}
            disabled={toggleLoading || skill.always}
            className="px-4 py-1.5 rounded-full text-xs font-medium bg-[#2d8a4e] text-white hover:bg-[#247a42] transition-colors disabled:opacity-50"
            style={{ fontFamily: "'DM Sans', sans-serif" }}
          >
            {toggleLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : "Install"}
          </button>
        </div>
      </div>
    </div>
  );
}
