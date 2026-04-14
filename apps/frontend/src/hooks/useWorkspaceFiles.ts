"use client";

import useSWR from "swr";
import { useApi } from "@/lib/api";

export interface FileEntry {
  name: string;
  path: string;
  type: "file" | "dir";
  size: number | null;
  modified_at: number;
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
    () => api.get(key!) as Promise<FileInfo>,
  );

  return {
    file: data ?? null,
    error,
    isLoading,
  };
}
