// apps/frontend/src/components/control/panels/cron/ToolsAllowlist.tsx
//
// Multi-select tool allowlist backed by the gateway `tools.catalog` RPC
// (Task 15). Empty selection means "all tools allowed" (the server default);
// a non-empty list narrows the run to just those tool ids.
//
// Degrades gracefully when the catalog is unavailable: users can still type
// arbitrary tool ids via the free-text "Add custom tool" input, which covers
// both the catalog-load-failed case and custom MCP/plugin tools.

"use client";

import { useMemo, useRef, useState } from "react";
import { X, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useGatewayRpc } from "@/hooks/useGatewayRpc";

// --- Catalog shape ---

interface CatalogTool {
  id: string;
  label?: string;
}

interface CatalogGroup {
  id: string;
  tools: CatalogTool[];
}

interface ToolsCatalogResponse {
  groups?: CatalogGroup[];
}

// --- Props ---

export interface ToolsAllowlistProps {
  /** Agent scope used to filter the catalog. If undefined, the RPC is called
   *  without an agentId and OpenClaw returns all tools the session can see. */
  agentId: string | undefined;
  value: string[] | undefined;
  onChange: (next: string[] | undefined) => void;
}

// --- Component ---

export function ToolsAllowlist({ agentId, value, onChange }: ToolsAllowlistProps) {
  const selected = value ?? [];
  const selectRef = useRef<HTMLSelectElement | null>(null);
  const [customInput, setCustomInput] = useState("");

  const { data, error } = useGatewayRpc<ToolsCatalogResponse>(
    "tools.catalog",
    {
      ...(agentId ? { agentId } : {}),
      includePlugins: true,
    },
  );

  const groups: CatalogGroup[] = useMemo(() => {
    if (error || !data?.groups) return [];
    return data.groups.filter((g) => Array.isArray(g.tools) && g.tools.length > 0);
  }, [data, error]);

  // Build the set of remaining (unselected) tools, preserving group structure.
  const availableGroups = useMemo(() => {
    if (groups.length === 0) return [];
    return groups
      .map((g) => ({
        id: g.id,
        tools: g.tools.filter((t) => !selected.includes(t.id)),
      }))
      .filter((g) => g.tools.length > 0);
  }, [groups, selected]);

  // --- Emit helpers ---

  const emit = (next: string[]) => {
    // Empty list -> undefined so the parent can spread-if-defined.
    onChange(next.length === 0 ? undefined : next);
  };

  const addTool = (toolId: string) => {
    const trimmed = toolId.trim();
    if (!trimmed) return;
    if (selected.includes(trimmed)) return;
    emit([...selected, trimmed]);
  };

  const removeTool = (toolId: string) => {
    emit(selected.filter((id) => id !== toolId));
  };

  // --- Handlers ---

  const handleDropdownChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const id = e.target.value;
    if (!id) return;
    addTool(id);
    // Reset the select back to the placeholder so the same tool can trigger
    // onChange again after removal.
    if (selectRef.current) selectRef.current.value = "";
  };

  const handleCustomAdd = () => {
    const v = customInput.trim();
    if (!v) return;
    addTool(v);
    setCustomInput("");
  };

  const handleCustomKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleCustomAdd();
    }
  };

  // --- Render ---

  const empty = selected.length === 0;
  const hasCatalog = availableGroups.length > 0;

  return (
    <div className="space-y-2" data-testid="tools-allowlist">
      {/* Selected chips */}
      {selected.length > 0 && (
        <ul className="flex flex-wrap gap-1.5">
          {selected.map((id) => (
            <li
              key={id}
              className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded bg-[#e8e3d9]"
            >
              <span className="font-mono">{id}</span>
              <button
                type="button"
                onClick={() => removeTool(id)}
                aria-label={`Remove tool ${id}`}
                className="inline-flex items-center justify-center rounded hover:bg-black/10 p-0.5"
              >
                <X className="h-3 w-3" />
              </button>
            </li>
          ))}
        </ul>
      )}

      {/* Catalog dropdown */}
      {hasCatalog && (
        <div>
          <select
            ref={selectRef}
            defaultValue=""
            onChange={handleDropdownChange}
            aria-label="Add tool from catalog"
            className="h-8 w-full rounded-md border border-[#e0dbd0] bg-[#faf7f2] px-2 text-sm"
          >
            <option value="">Add tool…</option>
            {availableGroups.map((group) => (
              <optgroup key={group.id} label={group.id}>
                {group.tools.map((tool) => (
                  <option key={tool.id} value={tool.id}>
                    {tool.label ? `${tool.label} (${tool.id})` : tool.id}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </div>
      )}

      {/* Free-text fallback — also useful for custom MCP tools not in catalog */}
      <div className="flex gap-1.5">
        <Input
          value={customInput}
          onChange={(e) => setCustomInput(e.target.value)}
          onKeyDown={handleCustomKeyDown}
          placeholder="Custom tool ID"
          aria-label="Custom tool ID"
          className="h-8 text-sm font-mono flex-1"
        />
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={handleCustomAdd}
          disabled={!customInput.trim()}
          aria-label="Add custom tool"
          className="h-8 px-2 text-xs"
        >
          <Plus className="h-3 w-3 mr-1" />
          Add
        </Button>
      </div>

      {/* Help text when empty */}
      {empty && (
        <p className="text-xs text-[#8a8578]">Empty = all tools allowed</p>
      )}
    </div>
  );
}
