"use client";

import { useState, useCallback } from "react";
import { Loader2, Plus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useGatewayRpcMutation } from "@/hooks/useGatewayRpc";

interface AgentCreateFormProps {
  existingIds: string[];
  onCreated: () => void;
  onCancel: () => void;
}

/** Normalize a display name to an agent ID (matches OpenClaw convention). */
function normalizeToId(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
}

export function AgentCreateForm({ existingIds, onCreated, onCancel }: AgentCreateFormProps) {
  const [name, setName] = useState("");
  const [emoji, setEmoji] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const callRpc = useGatewayRpcMutation();

  const normalizedId = normalizeToId(name);
  const isDuplicate = normalizedId !== "" && existingIds.includes(normalizedId);
  const isReserved = normalizedId === "main";
  const canCreate = name.trim() !== "" && !isDuplicate && !isReserved && !creating;

  const handleCreate = useCallback(async () => {
    if (!canCreate) return;

    setCreating(true);
    setError(null);

    try {
      await callRpc("agents.create", {
        name: name.trim(),
        workspace: `agents/${normalizedId}`,
        ...(emoji.trim() ? { emoji: emoji.trim() } : {}),
      });
      onCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setCreating(false);
    }
  }, [canCreate, callRpc, name, normalizedId, emoji, onCreated]);

  const clientError = isDuplicate
    ? "An agent with this name already exists"
    : isReserved
      ? "This name is reserved"
      : null;

  return (
    <div className="rounded-lg border border-border bg-card/30 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium">New Agent</h3>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md p-1 text-muted-foreground hover:text-foreground hover:bg-white/5 transition-colors"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="flex gap-3">
        {/* Emoji input */}
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">Emoji</label>
          <input
            type="text"
            value={emoji}
            onChange={(e) => setEmoji(e.target.value.slice(0, 2))}
            placeholder="🤖"
            disabled={creating}
            className="w-14 rounded-md border border-border bg-background px-2 py-1.5 text-center text-sm focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-50"
          />
        </div>

        {/* Name input */}
        <div className="flex-1 space-y-1">
          <label className="text-xs text-muted-foreground">Name</label>
          <input
            type="text"
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              setError(null);
            }}
            placeholder="e.g. Research Assistant"
            disabled={creating}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleCreate();
              if (e.key === "Escape") onCancel();
            }}
            autoFocus
            className="w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-50"
          />
          {normalizedId && !clientError && (
            <p className="text-[10px] text-muted-foreground">
              ID: {normalizedId}
            </p>
          )}
        </div>
      </div>

      {/* Error display */}
      {(clientError || error) && (
        <p className="text-xs text-red-500">{clientError || error}</p>
      )}

      {/* Actions */}
      <div className="flex justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={onCancel} disabled={creating}>
          Cancel
        </Button>
        <Button size="sm" onClick={handleCreate} disabled={!canCreate}>
          {creating ? (
            <Loader2 className="h-3 w-3 animate-spin mr-1" />
          ) : (
            <Plus className="h-3 w-3 mr-1" />
          )}
          Create
        </Button>
      </div>
    </div>
  );
}
