"use client";

// apps/frontend/src/components/control/panels/cron/AdvancedSection.tsx
//
// Body for the "Advanced" accordion section inside JobEditDialog.
// Extracted in Task 16 to keep JobEditDialog.tsx under the 400-line budget.

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { useAgents } from "@/hooks/useAgents";
import { cn } from "@/lib/utils";
import type { FormState } from "./formState";

export function AdvancedSection({
  form,
  update,
}: {
  form: FormState;
  update: <K extends keyof FormState>(key: K, value: FormState[K]) => void;
}) {
  // Confirm-before-enable for deleteAfterRun.
  const [confirmingDeleteAfterRun, setConfirmingDeleteAfterRun] = useState(false);

  // Agent picker reuses the same agents.list the sidebar uses.
  const { agents } = useAgents();

  return (
    <div className="space-y-4">
      {/* Delete after run (with inline confirmation) */}
      <div className="space-y-1">
        <label className="flex items-center gap-2 cursor-pointer">
          <Checkbox
            // Optimistic visual: show checked while the user is confirming,
            // so ticking the box doesn't appear to "do nothing" before
            // Enable anyway commits. Cancel reverts (form.deleteAfterRun
            // stays false).
            checked={form.deleteAfterRun || confirmingDeleteAfterRun}
            onCheckedChange={(checked) => {
              if (checked === true && !form.deleteAfterRun) {
                setConfirmingDeleteAfterRun(true);
              } else if (checked !== true) {
                setConfirmingDeleteAfterRun(false);
                update("deleteAfterRun", false);
              }
            }}
          />
          <span className="text-sm">Delete after first successful run</span>
        </label>
        <p className="text-xs text-[#8a8578] pl-6">
          One-shot jobs: remove this cron from the list as soon as it runs successfully.
        </p>

        {confirmingDeleteAfterRun && (
          <div className="mt-2 rounded-md bg-destructive/10 border border-destructive/20 px-3 py-2">
            <p className="text-sm text-destructive">
              Enabling this will <strong>delete this cron job</strong> after its first
              successful run. Typically used for one-time jobs; you would need to re-create
              it to run again.
            </p>
            <div className="mt-2 flex gap-1 justify-end">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setConfirmingDeleteAfterRun(false)}
              >
                Cancel
              </Button>
              <Button
                variant="destructive"
                size="sm"
                onClick={() => {
                  setConfirmingDeleteAfterRun(false);
                  update("deleteAfterRun", true);
                }}
              >
                Enable anyway
              </Button>
            </div>
          </div>
        )}
      </div>

      {/* Wake mode (segmented) */}
      <div className="space-y-1">
        <label className="text-xs font-medium text-[#8a8578]">Wake mode</label>
        <div className="flex gap-1">
          {([
            { id: "next-heartbeat", label: "Next heartbeat" },
            { id: "now", label: "Now" },
          ] as const).map(({ id, label }) => (
            <Button
              key={id}
              variant={form.wakeMode === id ? "default" : "outline"}
              size="sm"
              onClick={() => update("wakeMode", id)}
              className={cn("text-xs")}
            >
              {label}
            </Button>
          ))}
        </div>
        <p className="text-xs text-[#8a8578]">
          {form.wakeMode === "now"
            ? "Fire immediately when due."
            : "Wait for the next scheduler tick (low overhead)."}
        </p>
      </div>

      {/* Agent picker */}
      <div className="space-y-1">
        <label className="text-xs font-medium text-[#8a8578]">Agent</label>
        <select
          value={form.agentId ?? ""}
          onChange={(e) => update("agentId", e.target.value || undefined)}
          aria-label="Cron agent"
          className="h-8 w-full rounded-md border border-[#e0dbd0] bg-[#faf7f2] px-2 text-sm"
        >
          <option value="">(use default agent)</option>
          {agents.map((a) => (
            <option key={a.id} value={a.id}>
              {a.identity?.name || a.name || a.id}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
