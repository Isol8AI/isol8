"use client";

import { useState, useCallback } from "react";
import { Loader2, RefreshCw, FileText, Save, AlertCircle, FileWarning } from "lucide-react";
import { useGatewayRpc, useGatewayRpcMutation } from "@/hooks/useGatewayRpc";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { AgentFileEntry, AgentFilesResponse, AgentFileContent } from "./agents-types";

const KNOWN_FILES = [
  "SOUL.md", "MEMORY.md", "TOOLS.md", "IDENTITY.md",
  "USER.md", "HEARTBEAT.md", "BOOTSTRAP.md", "AGENTS.md",
];

export function AgentFilesTab({ agentId }: { agentId: string }) {
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
    return <Loader2 className="h-4 w-4 animate-spin text-[#8a8578] mt-4" />;
  }

  if (error) {
    return (
      <div className="mt-4 space-y-2">
        <p className="text-sm text-[#dc2626]">{error.message}</p>
        <Button variant="outline" size="sm" onClick={() => mutate()}>
          <RefreshCw className="h-3.5 w-3.5 mr-1.5" /> Retry
        </Button>
      </div>
    );
  }

  const fileMap = new Map(files.map((f) => [f.name, f]));
  const allFiles: AgentFileEntry[] = KNOWN_FILES.map((name) => {
    const existing = fileMap.get(name);
    return existing ?? { name, path: name, missing: true };
  });
  for (const f of files) {
    if (!KNOWN_FILES.includes(f.name)) {
      allFiles.push(f);
    }
  }

  return (
    <div className="mt-2 space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-[#8a8578]">{allFiles.length} files</p>
        <Button variant="ghost" size="sm" onClick={() => mutate()}>
          <RefreshCw className="h-3.5 w-3.5" />
        </Button>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-1">
        {allFiles.map((f) => (
          <button
            key={f.name}
            className={cn(
              "flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs text-left transition-colors",
              selectedFile === f.name
                ? "bg-[#e8f5e9] text-[#2d8a4e] border border-[#2d8a4e]/30"
                : "hover:bg-[#f3efe6]",
              f.missing && "opacity-50",
            )}
            onClick={() => handleFileClick(f.name)}
          >
            {f.missing ? (
              <FileWarning className="h-3 w-3 flex-shrink-0 text-[#8a8578]" />
            ) : (
              <FileText className="h-3 w-3 flex-shrink-0" />
            )}
            <span className="truncate">{f.name}</span>
            {f.size != null && !f.missing && (
              <span className="text-[10px] text-[#8a8578]/50 ml-auto flex-shrink-0">
                {f.size > 1024 ? `${(f.size / 1024).toFixed(1)}k` : `${f.size}b`}
              </span>
            )}
          </button>
        ))}
      </div>

      {selectedFile && (
        <div className="rounded-lg border border-[#e0dbd0] overflow-hidden">
          <div className="flex items-center justify-between px-3 py-2 bg-[#f3efe6]/50 border-b border-[#e0dbd0]">
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
            <div className="flex items-center gap-2 px-3 py-2 bg-[#fce4ec] border-b border-[#dc2626]/20">
              <AlertCircle className="h-3 w-3 text-[#dc2626] flex-shrink-0" />
              <span className="text-xs text-[#dc2626]">{saveError}</span>
            </div>
          )}

          {loadingFile ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-4 w-4 animate-spin text-[#8a8578]" />
            </div>
          ) : (
            <textarea
              className="w-full min-h-[300px] p-3 text-xs font-mono bg-white text-[#1a1a1a] resize-y focus:outline-none"
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
