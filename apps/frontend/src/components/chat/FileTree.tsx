"use client";

import * as React from "react";
import {
  ChevronRight, ChevronDown, FileText, FileCode, FileImage,
  FileJson, File, FolderOpen, FolderClosed, RefreshCw,
} from "lucide-react";
import type { FileEntry } from "@/hooks/useWorkspaceFiles";

const ICON_MAP: Record<string, React.ComponentType<{ className?: string }>> = {
  md: FileText, txt: FileText, log: FileText,
  py: FileCode, js: FileCode, ts: FileCode, tsx: FileCode, jsx: FileCode,
  sh: FileCode, bash: FileCode, rs: FileCode, go: FileCode, java: FileCode,
  c: FileCode, cpp: FileCode, rb: FileCode, php: FileCode, swift: FileCode,
  json: FileJson, yaml: FileJson, yml: FileJson, toml: FileJson,
  png: FileImage, jpg: FileImage, jpeg: FileImage, gif: FileImage,
  svg: FileImage, webp: FileImage,
};

function renderFileIcon(name: string, className: string): React.ReactElement {
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  const Icon = ICON_MAP[ext] ?? File;
  return <Icon className={className} />;
}

interface FileTreeNodeProps {
  entry: FileEntry;
  allEntries: FileEntry[];
  selectedPath: string | null;
  onSelect: (path: string) => void;
}

function FileTreeNode({ entry, allEntries, selectedPath, onSelect }: FileTreeNodeProps) {
  const [expanded, setExpanded] = React.useState(false);

  if (entry.type === "dir") {
    const children = allEntries.filter((e) => {
      const parentPath = entry.path + "/";
      return e.path.startsWith(parentPath) && !e.path.slice(parentPath.length).includes("/");
    });

    return (
      <div>
        <button
          onClick={() => setExpanded(!expanded)}
          className="w-full flex items-center gap-1.5 px-2 py-1 text-sm text-[#1a1a1a] hover:bg-[#e8e3d9] rounded transition-colors"
        >
          {expanded ? <ChevronDown className="h-3.5 w-3.5 text-[#8a8578] flex-shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 text-[#8a8578] flex-shrink-0" />}
          {expanded ? <FolderOpen className="h-4 w-4 text-[#8a8578] flex-shrink-0" /> : <FolderClosed className="h-4 w-4 text-[#8a8578] flex-shrink-0" />}
          <span className="truncate">{entry.name}</span>
        </button>
        {expanded && (
          <div className="pl-4">
            {children.map((child) => (
              <FileTreeNode
                key={child.path}
                entry={child}
                allEntries={allEntries}
                selectedPath={selectedPath}
                onSelect={onSelect}
              />
            ))}
          </div>
        )}
      </div>
    );
  }

  const isSelected = selectedPath === entry.path;

  return (
    <button
      onClick={() => onSelect(entry.path)}
      className={`w-full flex items-center gap-1.5 px-2 py-1 text-sm rounded transition-colors ${
        isSelected
          ? "bg-white text-[#1a1a1a] shadow-sm"
          : "text-[#1a1a1a] hover:bg-[#e8e3d9]"
      }`}
    >
      <span className="w-3.5 flex-shrink-0" />
      {renderFileIcon(entry.name, "h-4 w-4 text-[#8a8578] flex-shrink-0")}
      <span className="truncate">{entry.name}</span>
    </button>
  );
}

interface FileTreeProps {
  files: FileEntry[];
  selectedPath: string | null;
  onSelect: (path: string) => void;
  onRefresh: () => void;
  isLoading: boolean;
}

export function FileTree({ files, selectedPath, onSelect, onRefresh, isLoading }: FileTreeProps) {
  const rootEntries = React.useMemo(() => {
    if (files.length === 0) return [];
    const depths = files.map((f) => f.path.split("/").length);
    const minDepth = Math.min(...depths);
    return files.filter((f) => f.path.split("/").length === minDepth);
  }, [files]);

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between px-3 py-2 border-b border-[#e0dbd0]">
        <span className="text-xs font-medium text-[#8a8578] uppercase tracking-wide">Files</span>
        <button
          onClick={onRefresh}
          className="text-[#8a8578] hover:text-[#1a1a1a] transition-colors"
          title="Refresh file tree"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${isLoading ? "animate-spin" : ""}`} />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-2">
        {files.length === 0 && !isLoading ? (
          <div className="text-xs text-[#8a8578] text-center py-4">No files in workspace</div>
        ) : (
          rootEntries.map((entry) => (
            <FileTreeNode
              key={entry.path}
              entry={entry}
              allEntries={files}
              selectedPath={selectedPath}
              onSelect={onSelect}
            />
          ))
        )}
      </div>
    </div>
  );
}
