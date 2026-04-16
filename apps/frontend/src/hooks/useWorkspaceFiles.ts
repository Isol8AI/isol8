"use client";

import useSWR from "swr";
import { useApi } from "@/lib/api";

export interface FileEntry {
  name: string;
  path: string;
  type: "file" | "dir";
  size: number | null;
  modified_at: number;
  /**
   * Present only on frontend-synthesized "ghost" entries — allowlisted config
   * files that don't exist on disk yet. Backend responses never set this.
   */
  missing?: boolean;
}

export interface FileInfo {
  name: string;
  path: string;
  size: number;
  modified_at: number;
  content: string | null;
  binary: boolean;
  mime_type: string;
}

export function useWorkspaceTree(agentId: string | null) {
  const api = useApi();
  const key = agentId ? `/container/workspace/${agentId}/tree?recursive=true` : null;

  const { data, error, isLoading, mutate } = useSWR<{ files: FileEntry[] }>(
    key,
    () => api.get(key!) as Promise<{ files: FileEntry[] }>,
  );

  return {
    files: data?.files ?? [],
    error,
    isLoading,
    refresh: mutate,
  };
}

export function useWorkspaceFile(agentId: string | null, filePath: string | null) {
  const api = useApi();
  const key = agentId && filePath
    ? `/container/workspace/${agentId}/file?path=${encodeURIComponent(filePath)}`
    : null;

  const { data, error, isLoading } = useSWR<FileInfo>(
    key,
    () => api.get(key!) as Promise<FileInfo>,
  );

  return {
    file: data ?? null,
    error,
    isLoading,
  };
}

export function useConfigFiles(agentId: string | null) {
  const api = useApi();
  const key = agentId ? `/container/workspace/${agentId}/config-files` : null;

  const { data, error, isLoading, mutate } = useSWR<{ files: FileEntry[] }>(
    key,
    () => api.get(key!) as Promise<{ files: FileEntry[] }>,
  );

  return {
    files: data?.files ?? [],
    error,
    isLoading,
    refresh: mutate,
  };
}

export function useConfigFile(agentId: string | null, filePath: string | null) {
  const api = useApi();
  const key = agentId && filePath
    ? `/container/workspace/${agentId}/config-file?path=${encodeURIComponent(filePath)}`
    : null;

  const { data, error, isLoading } = useSWR<FileInfo>(
    key,
    async () => {
      try {
        return (await api.get(key!)) as FileInfo;
      } catch (err) {
        // A 404 on the config-file endpoint means "this is an allowlisted
        // filename, but it doesn't exist on disk yet". Synthesize an empty
        // editable buffer so the user can click a ghost entry, type content,
        // and save — the PUT endpoint creates the file on first save. Without
        // this, there is no UI path to create missing config files after
        // AgentFilesTab was removed.
        const status = (err as { status?: number }).status;
        if (status === 404 && filePath) {
          return {
            name: filePath.split("/").pop() ?? filePath,
            path: filePath,
            size: 0,
            modified_at: 0,
            content: "",
            binary: false,
            mime_type: "text/markdown",
          };
        }
        throw err;
      }
    },
  );

  return {
    file: data ?? null,
    error,
    isLoading,
  };
}
