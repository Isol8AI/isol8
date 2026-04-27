"use client";

import { useState } from "react";

import { AgentDetailPanel } from "@/components/chat/AgentDetailPanel";
import { GalleryItemRow } from "@/components/chat/GalleryItemRow";
import { useAgents } from "@/hooks/useAgents";
import { useCatalog, type CatalogAgent, type DeployResult } from "@/hooks/useCatalog";
import { capture } from "@/lib/analytics";

interface GallerySectionProps {
  onAgentDeployed?: (result: DeployResult) => void;
}

export function GallerySection({ onAgentDeployed }: GallerySectionProps) {
  const { agents, isLoading, deploy } = useCatalog();
  const { refresh: refreshAgents } = useAgents();
  const [selected, setSelected] = useState<CatalogAgent | null>(null);

  if (isLoading) return null;
  if (agents.length === 0) return null;

  const handleDeploy = async (slug: string) => {
    const result = await deploy(slug);
    capture("catalog_agent_deployed", {
      slug: result.slug,
      version: result.version,
    });
    await refreshAgents();
    onAgentDeployed?.(result);
    return result;
  };

  return (
    <>
      <div className="mt-4 border-t border-[#e0dbd0] pt-3">
        <h3 className="px-2 text-xs uppercase tracking-wide text-[#8a8578] mb-1">
          Gallery
        </h3>
        <div className="space-y-0.5">
          {agents.map((a) => (
            <GalleryItemRow
              key={a.slug}
              agent={a}
              onDeploy={handleDeploy}
              onOpenInfo={setSelected}
            />
          ))}
        </div>
      </div>
      <AgentDetailPanel
        agent={selected}
        onClose={() => setSelected(null)}
        onDeploy={handleDeploy}
      />
    </>
  );
}
