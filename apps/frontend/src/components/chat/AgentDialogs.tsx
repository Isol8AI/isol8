"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import type { Agent } from "@/hooks/useAgents";

/**
 * Normalize a display name to an agent ID. Mirrors OpenClaw's
 * `normalizeAgentId` (see openclaw `src/routing/session-key.ts`).
 */
function normalizeToId(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
}

// =============================================================================
// Create
// =============================================================================
//
// Each dialog is meant to be remounted by the parent (via a `key` prop tied
// to its open/target state) so its internal state initializes fresh on each
// open. That avoids the "reset state on close" useEffect anti-pattern that
// `react-hooks/set-state-in-effect` flags.

interface CreateProps {
  open: boolean;
  existingIds: string[];
  onCancel: () => void;
  onCreate: (name: string) => Promise<void>;
}

export function AgentCreateDialog({ open, existingIds, onCancel, onCreate }: CreateProps) {
  const [name, setName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const id = normalizeToId(name);
  const duplicate = id !== "" && existingIds.includes(id);
  const reserved = id === "main";
  const canSubmit = name.trim() !== "" && !duplicate && !reserved && !submitting;

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      await onCreate(name.trim());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setSubmitting(false);
    }
  };

  const clientError = duplicate
    ? "An agent with this name already exists"
    : reserved
      ? "This name is reserved"
      : null;

  return (
    <AlertDialog open={open} onOpenChange={(next) => !next && !submitting && onCancel()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>New agent</AlertDialogTitle>
          <AlertDialogDescription>
            Give your agent a name. Its workspace, tools, and memory are isolated from your other agents.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <div className="space-y-2">
          <input
            type="text"
            autoFocus
            value={name}
            onChange={(e) => { setName(e.target.value); setError(null); }}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleSubmit();
              if (e.key === "Escape") onCancel();
            }}
            placeholder="e.g. Research Assistant"
            disabled={submitting}
            className="w-full rounded-md border border-[#e0dbd0] bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#2d8a4e]/30 disabled:opacity-50"
          />
          {id && !clientError && (
            <p className="text-[11px] text-[#8a8578]">ID: {id}</p>
          )}
          {(clientError || error) && (
            <p className="text-xs text-red-500">{clientError || error}</p>
          )}
        </div>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={submitting}>Cancel</AlertDialogCancel>
          <AlertDialogAction onClick={handleSubmit} disabled={!canSubmit}>
            {submitting ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : null}
            Create
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

// =============================================================================
// Rename
// =============================================================================

interface RenameProps {
  agent: Agent | null;
  onCancel: () => void;
  onRename: (name: string) => Promise<void>;
}

export function AgentRenameDialog({ agent, onCancel, onRename }: RenameProps) {
  const [name, setName] = useState(agent?.identity?.name || agent?.name || agent?.id || "");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit = name.trim() !== "" && !submitting;

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      await onRename(name.trim());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setSubmitting(false);
    }
  };

  return (
    <AlertDialog open={agent !== null} onOpenChange={(next) => !next && !submitting && onCancel()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Rename agent</AlertDialogTitle>
          <AlertDialogDescription>
            The agent&apos;s ID stays the same — only the display name changes.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <div className="space-y-2">
          <input
            type="text"
            autoFocus
            value={name}
            onChange={(e) => { setName(e.target.value); setError(null); }}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleSubmit();
              if (e.key === "Escape") onCancel();
            }}
            disabled={submitting}
            className="w-full rounded-md border border-[#e0dbd0] bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#2d8a4e]/30 disabled:opacity-50"
          />
          {error && <p className="text-xs text-red-500">{error}</p>}
        </div>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={submitting}>Cancel</AlertDialogCancel>
          <AlertDialogAction onClick={handleSubmit} disabled={!canSubmit}>
            {submitting ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : null}
            Rename
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

// =============================================================================
// Delete
// =============================================================================

interface DeleteProps {
  agent: Agent | null;
  onCancel: () => void;
  onDelete: () => Promise<void>;
}

export function AgentDeleteDialog({ agent, onCancel, onDelete }: DeleteProps) {
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      await onDelete();
    } catch {
      setSubmitting(false);
    }
  };

  const displayName = agent?.identity?.name || agent?.name || agent?.id || "";

  return (
    <AlertDialog open={agent !== null} onOpenChange={(next) => !next && !submitting && onCancel()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete {displayName}?</AlertDialogTitle>
          <AlertDialogDescription>
            This removes the agent&apos;s workspace, files, and session history. This cannot be undone.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={submitting}>Cancel</AlertDialogCancel>
          <AlertDialogAction onClick={handleSubmit} disabled={submitting}>
            {submitting ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : null}
            Delete
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
