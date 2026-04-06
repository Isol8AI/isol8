"use client";

import { useState, useCallback, useMemo, useEffect } from "react";
import { Loader2, AlertCircle } from "lucide-react";
import { useGatewayRpc, useGatewayRpcMutation } from "@/hooks/useGatewayRpc";
import { useBilling } from "@/hooks/useBilling";
import { ModelSelector } from "@/components/chat/ModelSelector";
import type { AgentEntry, AgentIdentity, ConfigSnapshot } from "./agents-types";

function resolveModelPrimary(model?: string | { primary?: string; fallbacks?: string[] }): string | undefined {
  if (typeof model === "string") return model.trim() || undefined;
  if (typeof model === "object" && model) return model.primary?.trim() || undefined;
  return undefined;
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-[#8a8578]/60">{label}</div>
      <div className="text-sm font-medium truncate text-[#1a1a1a]">{value}</div>
    </div>
  );
}

export function AgentOverviewTab({ agentId, agent, onAgentUpdated }: { agentId: string; agent?: AgentEntry; onAgentUpdated?: () => void }) {
  const { data } = useGatewayRpc<Record<string, unknown>>(
    "agent.identity.get",
    { agentId },
  );
  const { data: configSnapshot, mutate: mutateConfig } = useGatewayRpc<ConfigSnapshot>("config.get");
  const callRpc = useGatewayRpcMutation();
  const [updatingModel, setUpdatingModel] = useState(false);
  const [modelError, setModelError] = useState<string | null>(null);

  const { fetchPricing } = useBilling();
  const [tierModel, setTierModel] = useState<string | undefined>(undefined);
  useEffect(() => {
    let cancelled = false;
    fetchPricing().then((pricing) => {
      if (!cancelled && pricing?.tier_model) {
        setTierModel(pricing.tier_model);
      }
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [fetchPricing]);

  const identity = (data || agent?.identity) as AgentIdentity | undefined;
  const configInner = configSnapshot?.config;

  const modelsCatalog = useMemo(
    () => configInner?.agents?.defaults?.models ?? {},
    [configInner?.agents?.defaults?.models],
  );

  const defaultModelPrimary = resolveModelPrimary(configInner?.agents?.defaults?.model);
  const agentConfigEntry = configInner?.agents?.list?.find(a => a?.id === agentId);
  const agentModelPrimary = resolveModelPrimary(agentConfigEntry?.model);
  const currentModel = agentModelPrimary || defaultModelPrimary || "";

  const handleModelChange = useCallback(async (newModel: string) => {
    setUpdatingModel(true);
    setModelError(null);
    try {
      await callRpc("agents.update", {
        agentId,
        ...(newModel ? { model: newModel } : { model: null }),
      });
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

  const selectorModels = useMemo(() => {
    const models: { id: string; name: string }[] = Object.entries(modelsCatalog).map(
      ([id, entry]) => ({ id, name: entry.alias || id.split("/").pop() || id })
    );
    if (currentModel && !modelsCatalog[currentModel]) {
      models.unshift({ id: currentModel, name: currentModel.split("/").pop() || currentModel });
    }
    return models;
  }, [modelsCatalog, currentModel]);

  return (
    <div className="space-y-4 mt-2">
      <div className="rounded-lg border border-[#e0dbd0] p-4 space-y-3 bg-white">
        <h3 className="text-sm font-medium text-[#1a1a1a]">Identity</h3>
        <div className="grid grid-cols-2 gap-3">
          <InfoRow label="Agent ID" value={agentId} />
          <InfoRow label="Name" value={identity?.name || agent?.name || "\u2014"} />
          <InfoRow label="Emoji" value={identity?.emoji || "\u2014"} />
          <InfoRow label="Theme" value={identity?.theme || "\u2014"} />
        </div>
      </div>

      <div className="rounded-lg border border-[#e0dbd0] p-4 space-y-3 bg-white">
        <h3 className="text-sm font-medium text-[#1a1a1a]">Model</h3>
        {selectorModels.length > 0 ? (
          <ModelSelector
            models={selectorModels}
            selectedModel={currentModel}
            onModelChange={handleModelChange}
            disabled={updatingModel || !configSnapshot?.hash}
            tierModel={tierModel}
          />
        ) : (
          <p className="text-xs text-[#8a8578]">
            {currentModel ? currentModel.split("/").pop() : "No models configured in gateway"}
          </p>
        )}
        {updatingModel && <Loader2 className="h-3.5 w-3.5 animate-spin text-[#8a8578]" />}
        {modelError && (
          <p className="text-xs text-[#dc2626] flex items-center gap-1">
            <AlertCircle className="h-3 w-3" /> {modelError}
          </p>
        )}
      </div>

      {data && (
        <details className="group">
          <summary className="text-xs text-[#8a8578]/60 cursor-pointer hover:text-[#8a8578]">
            Raw identity data
          </summary>
          <pre className="mt-2 text-xs bg-[#f3efe6] rounded-lg p-3 overflow-auto max-h-48 text-[#5a5549]">
            {JSON.stringify(data, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}
