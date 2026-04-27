"use client";

import { Info, Loader2, Plus } from "lucide-react";
import { useState } from "react";

import type { CatalogAgent } from "@/hooks/useCatalog";

interface GalleryItemRowProps {
  agent: CatalogAgent;
  onDeploy: (slug: string) => Promise<unknown>;
  onOpenInfo: (agent: CatalogAgent) => void;
}

export function GalleryItemRow({ agent, onDeploy, onOpenInfo }: GalleryItemRowProps) {
  const [deploying, setDeploying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleDeploy = async () => {
    setDeploying(true);
    setError(null);
    try {
      await onDeploy(agent.slug);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to deploy agent";
      setError(message);
    } finally {
      setDeploying(false);
    }
  };

  return (
    <div className="px-2 py-1">
      <div className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-white/60 transition-colors">
        <span
          aria-hidden
          className="flex items-center justify-center w-8 h-8 rounded-md bg-[#2d8a4e] text-white text-base flex-shrink-0"
        >
          {agent.emoji || "🤖"}
        </span>
        <span className="flex-1 text-sm text-[#1a1a1a] truncate">{agent.name}</span>
        <button
          type="button"
          aria-label={`Deploy ${agent.name}`}
          onClick={handleDeploy}
          disabled={deploying}
          className="p-1 rounded text-[#1a1a1a] hover:bg-white/60 disabled:opacity-50 transition-colors"
        >
          {deploying ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
        </button>
        <button
          type="button"
          aria-label={`Info about ${agent.name}`}
          onClick={() => onOpenInfo(agent)}
          className="p-1 rounded text-[#1a1a1a] hover:bg-white/60 transition-colors"
        >
          <Info className="w-4 h-4" />
        </button>
      </div>
      {error && (
        <div
          role="alert"
          className="mt-1 ml-10 mr-2 text-xs text-[#b32424] bg-[#fdecea] border border-[#f5c2c0] rounded px-2 py-1"
        >
          {error}
        </div>
      )}
    </div>
  );
}
