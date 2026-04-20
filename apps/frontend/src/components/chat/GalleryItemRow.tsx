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

  const handleDeploy = async () => {
    setDeploying(true);
    try {
      await onDeploy(agent.slug);
    } finally {
      setDeploying(false);
    }
  };

  return (
    <div className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-neutral-800">
      <span className="text-lg" aria-hidden>{agent.emoji || "🤖"}</span>
      <span className="flex-1 text-sm text-neutral-200 truncate">{agent.name}</span>
      <button
        type="button"
        aria-label={`Deploy ${agent.name}`}
        onClick={handleDeploy}
        disabled={deploying}
        className="p-1 rounded hover:bg-neutral-700 disabled:opacity-50"
      >
        {deploying ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
      </button>
      <button
        type="button"
        aria-label={`Info about ${agent.name}`}
        onClick={() => onOpenInfo(agent)}
        className="p-1 rounded hover:bg-neutral-700"
      >
        <Info className="w-4 h-4" />
      </button>
    </div>
  );
}
