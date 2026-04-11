"use client";

import { useCallback } from "react";
import { useGatewayRpc, useGatewayRpcMutation } from "@/hooks/useGatewayRpc";

/**
 * The gateway's `agents.list` RPC returns the agent's `model` field in one
 * of two shapes depending on whether the agent has an override:
 *
 *  - legacy flat string: `"amazon-bedrock/qwen.qwen3-vl-235b-a22b"`
 *  - structured object:  `{ primary: "amazon-bedrock/...", fallbacks: [...] }`
 *
 * Pre-OpenClaw-4.5 flattened this to a string in RPC responses; 4.5 returns
 * the structured shape as-is, which blew up anywhere on the frontend that
 * was calling `agent.model.split(...)` directly. Call sites MUST use
 * `getAgentModelString` to normalize.
 */
export type AgentModelRef = string | { primary?: string; fallbacks?: string[] };

export interface Agent {
  id: string;
  name?: string;
  identity?: { name?: string; emoji?: string; avatar?: string };
  model?: AgentModelRef;
}

/** Normalize an `Agent.model` field to a plain string (or undefined). */
export function getAgentModelString(agent: Pick<Agent, "model"> | undefined): string | undefined {
  const model = agent?.model;
  if (typeof model === "string") return model.trim() || undefined;
  if (model && typeof model === "object") return model.primary?.trim() || undefined;
  return undefined;
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
    async (params: { name: string }) => {
      // No `workspace` param — OpenClaw computes it from `agents.defaults.workspace`
      // in openclaw.json (set to `.openclaw/workspaces` by the backend so new
      // agents land on EFS).
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
    async (agentId: string, updates: { model?: string; name?: string }) => {
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
