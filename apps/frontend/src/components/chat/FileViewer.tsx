"use client";

import * as React from "react";
import { X, Copy } from "lucide-react";
import { FileTree } from "@/components/chat/FileTree";
import { FileContentViewer } from "@/components/chat/FileContentViewer";
import { useWorkspaceTree, useWorkspaceFile, useConfigFiles, useConfigFile } from "@/hooks/useWorkspaceFiles";

interface FileViewerProps {
  agentId: string | null;
  initialFilePath?: string | null;
  onClose: () => void;
}

type ViewerTab = "workspace" | "config";

function Breadcrumbs({ path, onNavigate }: { path: string; onNavigate: (segment: string) => void }) {
  const segments = path.split("/");
  return (
    <div className="flex items-center gap-1 text-sm text-[#8a8578] min-w-0">
      {segments.map((segment, i) => (
        <React.Fragment key={i}>
          {i > 0 && <span className="text-[#cdc7ba]">/</span>}
          <button
            onClick={() => onNavigate(segments.slice(0, i + 1).join("/"))}
            className="hover:text-[#1a1a1a] transition-colors truncate"
          >
            {segment}
          </button>
        </React.Fragment>
      ))}
    </div>
  );
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(timestamp: number): string {
  return new Date(timestamp * 1000).toLocaleString();
}

export function FileViewer({ agentId, initialFilePath, onClose }: FileViewerProps) {
  const [activeTab, setActiveTab] = React.useState<ViewerTab>("workspace");
  const [selectedPath, setSelectedPath] = React.useState<string | null>(initialFilePath ?? null);

  const relativeFilePath = React.useMemo(() => {
    if (!selectedPath) return null;
    const prefix = `agents/${agentId}/`;
    return selectedPath.startsWith(prefix) ? selectedPath.slice(prefix.length) : selectedPath;
  }, [selectedPath, agentId]);

  // Workspace tab data
  const { files: wsFiles, isLoading: wsTreeLoading, refresh: wsRefresh } = useWorkspaceTree(agentId);
  const { file: wsFile, isLoading: wsFileLoading, error: wsFileError } = useWorkspaceFile(
    activeTab === "workspace" ? agentId : null,
    activeTab === "workspace" ? relativeFilePath : null,
  );

  // Config tab data
  const { files: cfgFiles, isLoading: cfgTreeLoading, refresh: cfgRefresh } = useConfigFiles(agentId);
  const { file: cfgFile, isLoading: cfgFileLoading, error: cfgFileError } = useConfigFile(
    activeTab === "config" ? agentId : null,
    activeTab === "config" ? relativeFilePath : null,
  );

  const files = activeTab === "workspace" ? wsFiles : cfgFiles;
  const treeLoading = activeTab === "workspace" ? wsTreeLoading : cfgTreeLoading;
  const refresh = activeTab === "workspace" ? wsRefresh : cfgRefresh;
  const file = activeTab === "workspace" ? wsFile : cfgFile;
  const fileLoading = activeTab === "workspace" ? wsFileLoading : cfgFileLoading;
  const fileError = activeTab === "workspace" ? wsFileError : cfgFileError;

  React.useEffect(() => {
    if (initialFilePath) {
      setSelectedPath(initialFilePath);
      setActiveTab("workspace"); // chat-detected paths are always workspace paths
    }
  }, [initialFilePath]);

  function handleTabChange(tab: ViewerTab) {
    if (tab === activeTab) return;
    setActiveTab(tab);
    setSelectedPath(null);
  }

  function handleCopyContent() {
    if (file?.content) {
      navigator.clipboard.writeText(file.content).catch(() => {});
    }
  }

  return (
    <div className="file-viewer-panel">
      <style>{`
        .file-viewer-panel {
          display: flex;
          flex-direction: column;
          height: 100%;
          background: #faf7f2;
          border-left: 1px solid #e0dbd0;
        }
        .file-viewer-header {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 0 16px;
          height: 56px;
          border-bottom: 1px solid #e0dbd0;
          background: #faf7f2;
          flex-shrink: 0;
        }
        .file-viewer-body {
          display: flex;
          flex: 1;
          min-height: 0;
        }
        .file-viewer-tree {
          width: 220px;
          border-right: 1px solid #e0dbd0;
          flex-shrink: 0;
          overflow: hidden;
        }
        .file-viewer-content {
          flex: 1;
          min-width: 0;
          overflow: hidden;
        }
      `}</style>

      <div className="file-viewer-header">
        <div className="flex items-center gap-1">
          <button
            onClick={() => handleTabChange("workspace")}
            className={`px-3 py-1 text-sm rounded-md transition-colors ${
              activeTab === "workspace"
                ? "bg-white text-[#1a1a1a] shadow-sm font-medium"
                : "text-[#8a8578] hover:text-[#1a1a1a]"
            }`}
          >
            Workspace
          </button>
          <button
            onClick={() => handleTabChange("config")}
            className={`px-3 py-1 text-sm rounded-md transition-colors ${
              activeTab === "config"
                ? "bg-white text-[#1a1a1a] shadow-sm font-medium"
                : "text-[#8a8578] hover:text-[#1a1a1a]"
            }`}
          >
            Config
          </button>
        </div>

        <div className="flex-1" />

        {selectedPath && file && (
          <>
            <Breadcrumbs path={relativeFilePath ?? selectedPath} onNavigate={() => {}} />
            <span className="text-xs text-[#8a8578] flex-shrink-0 ml-2">
              {formatFileSize(file.size)} · {formatDate(file.modified_at)}
            </span>
            {file.content && (
              <button
                onClick={handleCopyContent}
                className="text-[#8a8578] hover:text-[#1a1a1a] transition-colors flex-shrink-0 ml-2"
                title="Copy file content"
              >
                <Copy className="h-4 w-4" />
              </button>
            )}
          </>
        )}

        <button
          onClick={onClose}
          className="text-[#8a8578] hover:text-[#1a1a1a] transition-colors flex-shrink-0 ml-2"
          title="Close file viewer"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="file-viewer-body">
        <div className="file-viewer-tree">
          <FileTree
            files={files}
            selectedPath={selectedPath}
            onSelect={setSelectedPath}
            onRefresh={() => refresh()}
            isLoading={treeLoading}
            emptyMessage={
              activeTab === "workspace"
                ? "No files yet. Your agent will create files here as it works."
                : "No config files found."
            }
          />
        </div>
        <div className="file-viewer-content">
          <FileContentViewer
            file={file}
            isLoading={fileLoading}
            error={fileError ?? null}
          />
        </div>
      </div>
    </div>
  );
}
