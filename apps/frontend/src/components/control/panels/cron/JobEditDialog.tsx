"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { DeliveryPicker } from "./DeliveryPicker";
import { JobEditSections, type JobEditSection } from "./JobEditSections";
import { SchedulePicker, scheduleIsValid } from "./SchedulePicker";

// Re-export shared form-state for backwards compatibility. The canonical
// home is now `./formState.ts`.
export {
  EMPTY_FORM,
  buildSchedule,
  jobToForm,
  type FormState,
  type ScheduleKind,
} from "./formState";

import type { FormState } from "./formState";

// --- Placeholder shared by empty accordion sections (Tasks 14-16) ---

function ComingSoon({ task }: { task: string }) {
  return (
    <div className="text-xs text-[#8a8578] italic">
      Coming soon ({task}).
    </div>
  );
}

// --- Dialog ---

export function JobEditDialog({
  initial,
  onSave,
  onCancel,
  saving,
}: {
  initial: FormState;
  onSave: (form: FormState) => void;
  onCancel: () => void;
  saving: boolean;
}) {
  const [form, setForm] = useState<FormState>(initial);
  const update = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const canSubmit = !!form.name.trim() && !!form.message.trim() && scheduleIsValid(form);

  const basicsBody = (
    <div className="space-y-4">
      {/* Name */}
      <div className="space-y-1">
        <label className="text-xs font-medium text-[#8a8578]">Name</label>
        <Input
          value={form.name}
          onChange={(e) => update("name", e.target.value)}
          placeholder="e.g. Daily summary"
          className="h-8 text-sm"
        />
      </div>

      {/* Schedule picker */}
      <SchedulePicker
        scheduleKind={form.scheduleKind}
        cronExpr={form.cronExpr}
        cronTz={form.cronTz}
        everyValue={form.everyValue}
        everyUnit={form.everyUnit}
        atDatetime={form.atDatetime}
        onFieldChange={update}
      />

      {/* Message */}
      <div className="space-y-1">
        <label className="text-xs font-medium text-[#8a8578]">Agent message</label>
        <textarea
          value={form.message}
          onChange={(e) => update("message", e.target.value)}
          placeholder="What should the agent do?"
          rows={3}
          className="w-full rounded-md border border-[#e0dbd0] bg-[#faf7f2] px-3 py-2 text-sm resize-none focus:outline-none focus:ring-1 focus:ring-[#06402B]/20"
        />
      </div>

      {/* Enabled toggle */}
      <label className="flex items-center gap-2 cursor-pointer">
        <input
          type="checkbox"
          checked={form.enabled}
          onChange={(e) => update("enabled", e.target.checked)}
          className="rounded"
        />
        <span className="text-sm">Enabled</span>
      </label>
    </div>
  );

  const deliveryBody = (
    <DeliveryPicker
      value={form.delivery}
      onChange={(d) => update("delivery", d)}
    />
  );

  const sections: JobEditSection[] = [
    { id: "basics", title: "Basics", defaultOpen: true, children: basicsBody },
    { id: "delivery", title: "Delivery", defaultOpen: true, children: deliveryBody },
    { id: "agent-execution", title: "Agent execution", defaultOpen: false, children: <ComingSoon task="Task 14" /> },
    { id: "failure-alerts", title: "Failure alerts", defaultOpen: false, children: <ComingSoon task="Task 16" /> },
    { id: "advanced", title: "Advanced", defaultOpen: false, children: <ComingSoon task="Task 16" /> },
  ];

  return (
    <div className="rounded-lg border border-[#e0dbd0] p-4 space-y-4 bg-white/80">
      <JobEditSections sections={sections} />

      {/* Actions */}
      <div className="flex gap-2 justify-end">
        <Button variant="outline" size="sm" onClick={onCancel} disabled={saving}>
          Cancel
        </Button>
        <Button size="sm" onClick={() => onSave(form)} disabled={!canSubmit || saving}>
          {saving && <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />}
          Save
        </Button>
      </div>
    </div>
  );
}
