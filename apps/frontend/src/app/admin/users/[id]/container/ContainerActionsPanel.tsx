"use client";

import * as React from "react";
import { useRouter } from "next/navigation";

import { ConfirmActionDialog } from "@/components/admin/ConfirmActionDialog";
import { ErrorBanner } from "@/components/admin/ErrorBanner";
import { Button } from "@/components/ui/button";
import {
  reprovisionContainer,
  resizeContainer,
  startContainer,
  stopContainer,
} from "@/app/admin/_actions/container";

const TIERS = ["free", "starter", "pro", "enterprise"] as const;
type Tier = (typeof TIERS)[number];

export interface ContainerActionsPanelProps {
  userId: string;
  /** Current plan tier — pre-selects the resize dropdown so the operator only changes one thing. */
  currentTier?: string;
}

/**
 * Client island for the per-user container lifecycle actions. The four
 * non-resize actions all use the user_id as the typed-confirm phrase
 * (CEO S5). Resize additionally requires picking a target tier in a small
 * inline form before opening the confirm dialog.
 */
export function ContainerActionsPanel({ userId, currentTier }: ContainerActionsPanelProps) {
  const router = useRouter();
  const [error, setError] = React.useState<string | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);
  const [tier, setTier] = React.useState<Tier>(() => {
    if (currentTier && (TIERS as readonly string[]).includes(currentTier)) {
      return currentTier as Tier;
    }
    return "starter";
  });

  function clearStatus() {
    setError(null);
    setNotice(null);
  }

  function applyResult(label: string, ok: boolean, errMsg?: string) {
    if (ok) {
      setNotice(`${label} succeeded.`);
      router.refresh();
    } else {
      setError(`${label} failed: ${errMsg ?? "unknown_error"}`);
    }
  }

  // Handlers are plain async functions — React Compiler memoizes them. Manual
  // useCallback would require listing applyResult/clearStatus in deps which
  // tangles with the linter's "preserve manual memoization" rule.
  async function handleReprovision() {
    clearStatus();
    const result = await reprovisionContainer(userId);
    applyResult("Reprovision", result.ok, result.error);
  }

  async function handleStop() {
    clearStatus();
    const result = await stopContainer(userId);
    applyResult("Stop", result.ok, result.error);
  }

  async function handleStart() {
    clearStatus();
    const result = await startContainer(userId);
    applyResult("Start", result.ok, result.error);
  }

  async function handleResize() {
    clearStatus();
    const result = await resizeContainer(userId, tier);
    applyResult(`Resize to ${tier}`, result.ok, result.error);
  }

  return (
    <div className="space-y-3 rounded-md border border-white/10 bg-white/[0.02] p-4">
      <h2 className="text-sm font-medium uppercase tracking-wide text-zinc-400">
        Container actions
      </h2>
      {error ? <ErrorBanner error={error} variant="error" /> : null}
      {notice ? <ErrorBanner error={notice} variant="info" /> : null}

      {/* Lifecycle */}
      <div className="flex flex-wrap gap-2">
        <ConfirmActionDialog
          confirmText={userId}
          actionLabel="Reprovision container"
          destructive
          onConfirm={handleReprovision}
        >
          <Button type="button" variant="destructive" size="sm">
            Reprovision
          </Button>
        </ConfirmActionDialog>
        <ConfirmActionDialog
          confirmText={userId}
          actionLabel="Stop container"
          destructive
          onConfirm={handleStop}
        >
          <Button type="button" variant="destructive" size="sm">
            Stop
          </Button>
        </ConfirmActionDialog>
        <ConfirmActionDialog
          confirmText={userId}
          actionLabel="Start container"
          onConfirm={handleStart}
        >
          <Button type="button" variant="outline" size="sm">
            Start
          </Button>
        </ConfirmActionDialog>
      </div>

      {/* Resize */}
      <div className="space-y-2 rounded-md border border-white/5 bg-white/[0.01] p-3">
        <h3 className="text-xs font-medium uppercase tracking-wide text-zinc-500">
          Resize container
        </h3>
        <div className="flex flex-wrap items-center gap-2">
          <label className="text-xs text-zinc-400" htmlFor="resize-tier">
            Target tier
          </label>
          <select
            id="resize-tier"
            value={tier}
            onChange={(e) => setTier(e.target.value as Tier)}
            className="h-9 rounded-md border border-input bg-background px-3 text-sm text-zinc-100"
          >
            {TIERS.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
          <ConfirmActionDialog
            confirmText={userId}
            actionLabel={`Resize to ${tier}`}
            onConfirm={handleResize}
          >
            <Button type="button" variant="default" size="sm">
              Resize
            </Button>
          </ConfirmActionDialog>
        </div>
      </div>
    </div>
  );
}
