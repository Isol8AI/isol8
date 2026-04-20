"use client";

import { X } from "lucide-react";

import type { CatalogAgent } from "@/hooks/useCatalog";

interface AgentDetailPanelProps {
  agent: CatalogAgent | null;
  onClose: () => void;
  onDeploy: (slug: string) => Promise<unknown>;
}

export function AgentDetailPanel({ agent, onClose, onDeploy }: AgentDetailPanelProps) {
  if (!agent) return null;

  return (
    <aside className="fixed right-0 top-0 h-full w-96 bg-neutral-900 border-l border-neutral-800 p-6 overflow-y-auto">
      <div className="flex items-start justify-between">
        <div>
          <div className="text-4xl mb-2">{agent.emoji || "🤖"}</div>
          <h2 className="text-xl font-semibold text-neutral-100">{agent.name}</h2>
          <p className="text-sm text-neutral-400 mt-1">v{agent.version}</p>
        </div>
        <button
          type="button"
          aria-label="Close"
          onClick={onClose}
          className="p-1 rounded hover:bg-neutral-800"
        >
          <X className="w-5 h-5" />
        </button>
      </div>

      {agent.vibe && (
        <section className="mt-6">
          <h3 className="text-xs uppercase tracking-wide text-neutral-500 mb-1">Vibe</h3>
          <p className="text-sm text-neutral-200">{agent.vibe}</p>
        </section>
      )}

      {agent.description && (
        <section className="mt-4">
          <h3 className="text-xs uppercase tracking-wide text-neutral-500 mb-1">About</h3>
          <p className="text-sm text-neutral-200">{agent.description}</p>
        </section>
      )}

      {agent.suggested_model && (
        <section className="mt-4">
          <h3 className="text-xs uppercase tracking-wide text-neutral-500 mb-1">Designed for</h3>
          <p className="text-sm text-neutral-200">
            Model: {agent.suggested_model}
            <br />
            <span className="text-xs text-neutral-500">
              Your tier&apos;s default model will be used when you deploy.
            </span>
          </p>
        </section>
      )}

      {agent.suggested_channels.length > 0 && (
        <section className="mt-4">
          <h3 className="text-xs uppercase tracking-wide text-neutral-500 mb-1">Suggested channels</h3>
          <div className="flex flex-wrap gap-1">
            {agent.suggested_channels.map((c) => (
              <span key={c} className="text-xs px-2 py-0.5 rounded bg-neutral-800 text-neutral-300">{c}</span>
            ))}
          </div>
        </section>
      )}

      {agent.required_skills.length > 0 && (
        <section className="mt-4">
          <h3 className="text-xs uppercase tracking-wide text-neutral-500 mb-1">Skills it will enable</h3>
          <div className="flex flex-wrap gap-1">
            {agent.required_skills.map((s) => (
              <span key={s} className="text-xs px-2 py-0.5 rounded bg-neutral-800 text-neutral-300">{s}</span>
            ))}
          </div>
        </section>
      )}

      <button
        type="button"
        onClick={() => onDeploy(agent.slug).then(onClose)}
        className="mt-6 w-full py-2 rounded bg-indigo-600 hover:bg-indigo-500 text-white font-medium"
      >
        Deploy {agent.name}
      </button>
    </aside>
  );
}
