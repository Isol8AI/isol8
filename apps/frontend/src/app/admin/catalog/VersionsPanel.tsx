"use client";

import { useState } from "react";
import { X } from "lucide-react";

import type { CatalogVersion } from "@/app/admin/_lib/api";

export interface VersionsPanelProps {
  slug: string | null;
  versions: CatalogVersion[] | null;
  onClose: () => void;
}

/**
 * Right-side drawer that renders a slug's publish history. The bearer token
 * lives server-side, so this component never fetches — the parent page loads
 * versions via a Server Action and threads them down as a prop. The three
 * states are encoded in the `versions` prop:
 *
 * - `null`: request in flight — render "Loading…"
 * - `[]`  : no versions (edge case for a brand-new slug) — render empty state
 * - array : render rows with a per-version expand-to-show-manifest toggle
 *
 * `slug === null` hides the panel entirely so the caller can use a single
 * always-mounted instance and toggle visibility by setting/clearing the slug.
 */
export function VersionsPanel({ slug, versions, onClose }: VersionsPanelProps) {
  const [openVersion, setOpenVersion] = useState<number | null>(null);

  if (!slug) return null;

  return (
    <aside className="fixed right-0 top-0 h-full w-96 bg-neutral-900 border-l border-neutral-800 p-6 overflow-y-auto z-50">
      <div className="flex items-start justify-between mb-4">
        <h3 className="text-lg font-semibold text-neutral-100">
          {slug} versions
        </h3>
        <button
          type="button"
          aria-label="Close"
          onClick={onClose}
          className="p-1 rounded hover:bg-neutral-800"
        >
          <X className="w-5 h-5" />
        </button>
      </div>

      {versions === null && (
        <p className="text-sm text-neutral-400">Loading…</p>
      )}
      {versions?.length === 0 && (
        <p className="text-sm text-neutral-400">No versions found.</p>
      )}
      {versions?.map((v) => (
        <div
          key={v.version}
          className="mb-4 border border-neutral-800 rounded p-3"
        >
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-neutral-200">
              v{v.version}
            </span>
            <span className="text-xs text-neutral-500">{v.published_at}</span>
          </div>
          <div className="text-xs text-neutral-500 mt-1">
            Published by {v.published_by}
          </div>
          <button
            type="button"
            onClick={() =>
              setOpenVersion(openVersion === v.version ? null : v.version)
            }
            className="mt-2 text-xs text-indigo-400 hover:underline"
          >
            {openVersion === v.version ? "Hide" : "Show"} manifest
          </button>
          {openVersion === v.version && (
            <pre className="mt-2 text-xs bg-neutral-950 text-neutral-300 p-2 rounded overflow-x-auto">
              {JSON.stringify(v.manifest, null, 2)}
            </pre>
          )}
        </div>
      ))}
    </aside>
  );
}
