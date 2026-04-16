// apps/frontend/src/components/control/panels/cron/FallbackModelList.tsx
//
// Ordered list editor for agentTurn fallback model ids (Task 14).
//
// Design note: we deliberately use a plain <Input> for each row instead of the
// chat `ModelSelector` component. The existing ModelSelector requires a
// `models: Model[]` catalog + `selectedModel` string (no allowNull support),
// and the cron panel doesn't have a models catalog handy. OpenClaw itself
// accepts any string as a model id, so a free-text input matches the intent
// and gives users maximal flexibility. If we later gain a shared model
// catalog, revisit.

"use client";

import { ArrowUp, ArrowDown, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export interface FallbackModelListProps {
  value: string[] | undefined;
  onChange: (next: string[] | undefined) => void;
}

export function FallbackModelList({ value, onChange }: FallbackModelListProps) {
  const rows = value ?? [];

  const emit = (next: string[]) => {
    // If the list empties out, collapse to `undefined` so the caller can
    // spread-if-defined and omit the field from the payload entirely.
    onChange(next.length === 0 ? undefined : next);
  };

  const updateRow = (index: number, v: string) => {
    const next = rows.slice();
    next[index] = v;
    emit(next);
  };

  const moveUp = (index: number) => {
    if (index <= 0) return;
    const next = rows.slice();
    [next[index - 1], next[index]] = [next[index], next[index - 1]];
    emit(next);
  };

  const moveDown = (index: number) => {
    if (index >= rows.length - 1) return;
    const next = rows.slice();
    [next[index], next[index + 1]] = [next[index + 1], next[index]];
    emit(next);
  };

  const removeRow = (index: number) => {
    const next = rows.slice();
    next.splice(index, 1);
    emit(next);
  };

  const addRow = () => {
    emit([...rows, ""]);
  };

  return (
    <div className="space-y-2">
      {rows.length === 0 ? (
        <p className="text-xs text-[#8a8578] italic">
          No fallback models. If the primary model fails, the run will error.
        </p>
      ) : (
        <ol className="space-y-1.5">
          {rows.map((row, index) => (
            <li key={index} className="flex items-center gap-1.5">
              <span className="text-xs text-[#8a8578] w-5 tabular-nums text-right">
                {index + 1}.
              </span>
              <Input
                value={row}
                onChange={(e) => updateRow(index, e.target.value)}
                placeholder="e.g. anthropic.claude-sonnet-4"
                className="h-8 text-sm font-mono flex-1"
                aria-label={`Fallback model ${index + 1}`}
              />
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={() => moveUp(index)}
                disabled={index === 0}
                aria-label={`Move fallback ${index + 1} up`}
                className="h-8 w-8 p-0"
              >
                <ArrowUp className="h-3.5 w-3.5" />
              </Button>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={() => moveDown(index)}
                disabled={index === rows.length - 1}
                aria-label={`Move fallback ${index + 1} down`}
                className="h-8 w-8 p-0"
              >
                <ArrowDown className="h-3.5 w-3.5" />
              </Button>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={() => removeRow(index)}
                aria-label={`Remove fallback ${index + 1}`}
                className="h-8 w-8 p-0 text-destructive hover:text-destructive"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </li>
          ))}
        </ol>
      )}

      <Button
        type="button"
        size="sm"
        variant="outline"
        onClick={addRow}
        className="h-7 text-xs"
      >
        <Plus className="h-3 w-3 mr-1" />
        Add fallback
      </Button>
    </div>
  );
}
