"use client";

import { useState, useCallback } from "react";
import {
  Loader2,
  RefreshCw,
  Search,
  Download,
  ArrowUpCircle,
  Trash2,
} from "lucide-react";
import { useGatewayRpc, useGatewayRpcMutation } from "@/hooks/useGatewayRpc";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface SkillStatusEntry {
  name: string;
  description: string;
  source: string;
  skillKey: string;
  emoji?: string;
  [key: string]: unknown;
}

interface SkillStatusReport {
  skills: SkillStatusEntry[];
}

interface ExecResult {
  stdout?: string;
  stderr?: string;
  exitCode?: number;
  output?: string;
  [key: string]: unknown;
}

export function ClawHubTab({ agentId: _agentId }: { agentId?: string }) {
  const callRpc = useGatewayRpcMutation();
  const { data: raw, mutate: mutateSkills } = useGatewayRpc<SkillStatusReport | SkillStatusEntry[]>(
    "skills.status",
    {},
  );

  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<string | null>(null);
  const [searchLoading, setSearchLoading] = useState(false);
  const [installLoading, setInstallLoading] = useState<string | null>(null);
  const [updateLoading, setUpdateLoading] = useState<string | null>(null);
  const [removeLoading, setRemoveLoading] = useState<string | null>(null);

  // Filter installed ClawHub skills from skills.status
  const allSkills: SkillStatusEntry[] = Array.isArray(raw) ? raw : raw?.skills ?? [];
  const installedFromClawHub = allSkills.filter((s) => s.source === "openclaw-managed");

  const extractOutput = (result: unknown): string => {
    if (typeof result === "string") return result;
    const r = result as ExecResult;
    return r.stdout || r.output || r.stderr || JSON.stringify(result, null, 2);
  };

  const handleSearch = useCallback(async () => {
    if (!searchQuery.trim()) return;
    setSearchLoading(true);
    setSearchResults(null);
    try {
      const result = await callRpc("exec.run", {
        command: "clawhub",
        args: ["search", searchQuery.trim(), "--limit", "10", "--no-input"],
      });
      setSearchResults(extractOutput(result));
    } catch (err) {
      console.error("ClawHub search failed:", err);
      setSearchResults(
        err instanceof Error ? `Search failed: ${err.message}` : "Search failed"
      );
    } finally {
      setSearchLoading(false);
    }
  }, [searchQuery, callRpc]);

  const handleInstall = async (slug: string) => {
    setInstallLoading(slug);
    try {
      await callRpc("exec.run", {
        command: "clawhub",
        args: ["install", slug, "--no-input"],
      });
      mutateSkills();
    } catch (err) {
      console.error("ClawHub install failed:", err);
    } finally {
      setInstallLoading(null);
    }
  };

  const handleUpdate = async (slug: string) => {
    setUpdateLoading(slug);
    try {
      await callRpc("exec.run", {
        command: "clawhub",
        args: ["update", slug, "--no-input"],
      });
      mutateSkills();
    } catch (err) {
      console.error("ClawHub update failed:", err);
    } finally {
      setUpdateLoading(null);
    }
  };

  const handleRemove = async (slug: string) => {
    setRemoveLoading(slug);
    try {
      await callRpc("exec.run", {
        command: "rm",
        args: ["-rf", `skills/${slug}`],
      });
      mutateSkills();
    } catch (err) {
      console.error("ClawHub remove failed:", err);
    } finally {
      setRemoveLoading(null);
    }
  };

  return (
    <div className="p-6 space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">ClawHub</h2>
        <Button variant="ghost" size="sm" onClick={() => mutateSkills()}>
          <RefreshCw className="h-3.5 w-3.5" />
        </Button>
      </div>

      {/* Search */}
      <div className="space-y-2">
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              placeholder="Search skills on ClawHub..."
              className="pl-8 h-8 text-sm"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleSearch();
              }}
            />
          </div>
          <Button
            size="sm"
            className="text-xs"
            onClick={handleSearch}
            disabled={searchLoading || !searchQuery.trim()}
          >
            {searchLoading ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              "Search"
            )}
          </Button>
        </div>

        {/* Search results */}
        {searchResults !== null && (
          <div className="space-y-2">
            <h3 className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              Search Results
            </h3>
            <div className="rounded-lg border border-border bg-card/30 p-3">
              <pre className="text-xs font-mono whitespace-pre-wrap break-words text-foreground/80">
                {searchResults}
              </pre>
            </div>
            <p className="text-xs text-muted-foreground">
              To install a skill, type the slug below:
            </p>
            <InstallBySlug onInstall={handleInstall} loading={installLoading} />
          </div>
        )}
      </div>

      {/* Installed from ClawHub */}
      <div className="space-y-2">
        <h3 className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          Installed from ClawHub ({installedFromClawHub.length})
        </h3>

        {installedFromClawHub.length === 0 && (
          <p className="text-xs text-muted-foreground">
            No skills installed from ClawHub yet.
          </p>
        )}

        {installedFromClawHub.map((skill) => (
          <div
            key={skill.skillKey || skill.name}
            className="rounded-lg border border-border p-4 space-y-2 bg-card/30"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  {skill.emoji && (
                    <span className="text-base flex-shrink-0">{skill.emoji}</span>
                  )}
                  <h4 className="text-sm font-medium truncate">{skill.name}</h4>
                </div>
                {skill.description && (
                  <p className="text-xs text-muted-foreground mt-1 line-clamp-2">
                    {skill.description}
                  </p>
                )}
              </div>
              <div className="flex items-center gap-1">
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 px-2 text-xs gap-1"
                  onClick={() => handleUpdate(skill.name)}
                  disabled={updateLoading !== null}
                  title="Update"
                >
                  {updateLoading === skill.name ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <ArrowUpCircle className="h-3 w-3" />
                  )}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 px-2 text-xs gap-1 text-destructive hover:text-destructive"
                  onClick={() => handleRemove(skill.name)}
                  disabled={removeLoading !== null}
                  title="Remove"
                >
                  {removeLoading === skill.name ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <Trash2 className="h-3 w-3" />
                  )}
                </Button>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// --- Install by slug mini-form ---

function InstallBySlug({
  onInstall,
  loading,
}: {
  onInstall: (slug: string) => void;
  loading: string | null;
}) {
  const [slug, setSlug] = useState("");

  return (
    <div className="flex gap-2">
      <Input
        placeholder="skill-slug"
        className="h-8 text-xs font-mono"
        value={slug}
        onChange={(e) => setSlug(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && slug.trim()) onInstall(slug.trim());
        }}
      />
      <Button
        size="sm"
        className="text-xs gap-1.5"
        onClick={() => {
          if (slug.trim()) onInstall(slug.trim());
        }}
        disabled={loading !== null || !slug.trim()}
      >
        {loading ? (
          <Loader2 className="h-3 w-3 animate-spin" />
        ) : (
          <Download className="h-3 w-3" />
        )}
        Install
      </Button>
    </div>
  );
}
