"use client";

import { Loader2, X } from "lucide-react";
import { useState } from "react";

import type { CatalogAgent } from "@/hooks/useCatalog";

interface AgentDetailPanelProps {
  agent: CatalogAgent | null;
  onClose: () => void;
  onDeploy: (slug: string) => Promise<unknown>;
}

export function AgentDetailPanel({ agent, onClose, onDeploy }: AgentDetailPanelProps) {
  const [deploying, setDeploying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!agent) return null;

  const handleDeploy = async () => {
    setDeploying(true);
    setError(null);
    try {
      await onDeploy(agent.slug);
      onClose();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to deploy agent";
      setError(message);
    } finally {
      setDeploying(false);
    }
  };

  return (
    <aside
      className="fixed right-0 top-0 z-50 h-full w-96 bg-white border-l border-[#e0dbd0] p-6 overflow-y-auto shadow-[-2px_0_8px_rgba(0,0,0,0.06)]"
    >
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center justify-center w-12 h-12 rounded-md bg-[#2d8a4e] text-white text-2xl mb-2">
            {agent.emoji || "🤖"}
          </div>
          <h2 className="text-xl font-semibold text-[#1a1a1a]">{agent.name}</h2>
          <p className="text-sm text-[#8a8578] mt-1">v{agent.version}</p>
        </div>
        <button
          type="button"
          aria-label="Close"
          onClick={onClose}
          className="p-1 rounded text-[#8a8578] hover:bg-[#f3efe6] hover:text-[#1a1a1a] transition-colors"
        >
          <X className="w-5 h-5" />
        </button>
      </div>

      {agent.vibe && (
        <section className="mt-6">
          <h3 className="text-xs uppercase tracking-wide text-[#8a8578] mb-1">Vibe</h3>
          <p className="text-sm text-[#1a1a1a]">{agent.vibe}</p>
        </section>
      )}

      {agent.description && (
        <section className="mt-4">
          <h3 className="text-xs uppercase tracking-wide text-[#8a8578] mb-1">About</h3>
          <p className="text-sm text-[#1a1a1a]">{agent.description}</p>
        </section>
      )}

      {agent.suggested_model && (
        <section className="mt-4">
          <h3 className="text-xs uppercase tracking-wide text-[#8a8578] mb-1">Designed for</h3>
          <p className="text-sm text-[#1a1a1a]">
            Model: {agent.suggested_model}
            <br />
            <span className="text-xs text-[#8a8578]">
              Your tier&apos;s default model will be used when you deploy.
            </span>
          </p>
        </section>
      )}

      {agent.suggested_channels.length > 0 && (
        <section className="mt-4">
          <h3 className="text-xs uppercase tracking-wide text-[#8a8578] mb-1">Suggested channels</h3>
          <div className="flex flex-wrap gap-1">
            {agent.suggested_channels.map((c) => (
              <span
                key={c}
                className="text-xs px-2 py-0.5 rounded bg-[#f3efe6] text-[#1a1a1a] border border-[#e0dbd0]"
              >
                {c}
              </span>
            ))}
          </div>
        </section>
      )}

      {agent.required_skills.length > 0 && (
        <section className="mt-4">
          <h3 className="text-xs uppercase tracking-wide text-[#8a8578] mb-1">Skills it will enable</h3>
          <div className="flex flex-wrap gap-1">
            {agent.required_skills.map((s) => (
              <span
                key={s}
                className="text-xs px-2 py-0.5 rounded bg-[#f3efe6] text-[#1a1a1a] border border-[#e0dbd0]"
              >
                {s}
              </span>
            ))}
          </div>
        </section>
      )}

      {error && (
        <div
          role="alert"
          className="mt-6 text-sm text-[#b32424] bg-[#fdecea] border border-[#f5c2c0] rounded px-3 py-2"
        >
          {error}
        </div>
      )}

      <button
        type="button"
        onClick={handleDeploy}
        disabled={deploying}
        className="mt-4 w-full py-2 rounded bg-[#2d8a4e] hover:bg-[#247040] disabled:opacity-60 disabled:cursor-not-allowed text-white font-medium flex items-center justify-center gap-2 transition-colors"
      >
        {deploying ? (
          <>
            <Loader2 className="w-4 h-4 animate-spin" />
            Deploying…
          </>
        ) : (
          <>Deploy {agent.name}</>
        )}
      </button>
    </aside>
  );
}
