"use client";

import { useCallback } from "react";
import { useGatewayRpc, useGatewayRpcMutation } from "@/hooks/useGatewayRpc";

export interface Agent {
  id: string;
  name?: string;
  identity?: { name?: string; emoji?: string; avatar?: string };
  model?: string;
}

interface AgentsListResponse {
  defaultId?: string;
  agents?: Agent[];
}

export function useAgents() {
  const { data, error, isLoading, mutate } =
    useGatewayRpc<AgentsListResponse>("agents.list");
  const callRpc = useGatewayRpcMutation();

  const agents = data?.agents ?? [];
  const defaultId = data?.defaultId;

  const createAgent = useCallback(
    async (params: { name: string; workspace: string; emoji?: string }) => {
      await callRpc("agents.create", params);
      mutate();
    },
    [callRpc, mutate],
  );

  const deleteAgent = useCallback(
    async (agentId: string) => {
      await callRpc("agents.delete", { agentId, deleteFiles: true });
      mutate();
    },
    [callRpc, mutate],
  );

  const updateAgent = useCallback(
    async (agentId: string, updates: { model?: string }) => {
      await callRpc("agents.update", { agentId, ...updates });
      mutate();
    },
    [callRpc, mutate],
  );

  return {
    agents,
    defaultId,
    isLoading,
    error,
    refresh: () => mutate(),
    createAgent,
    deleteAgent,
    updateAgent,
  };
}
