"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { AdvancedSection } from "./AdvancedSection";
import { DeliveryPicker } from "./DeliveryPicker";
import { FailureAlertsSection } from "./FailureAlertsSection";
import { FallbackModelList } from "./FallbackModelList";
import { JobEditSections, type JobEditSection } from "./JobEditSections";
import { SchedulePicker, scheduleIsValid } from "./SchedulePicker";
import { ToolsAllowlist } from "./ToolsAllowlist";

// Re-export shared form-state for backwards compatibility. The canonical
// home is now `./formState.ts`.
export {
  EMPTY_FORM,
  buildSchedule,
  buildFailureAlertPayload,
  jobToForm,
  type FormState,
  type ScheduleKind,
} from "./formState";

import type { FormState } from "./formState";

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
        onFieldChange={(key, value) =>
          // SchedulePickerFields is a strict subset of FormState, so the
          // key/value pairing is always valid at runtime. TS can't prove the
          // indexed-access contravariance on its own.
          update(key as keyof FormState, value as FormState[keyof FormState])
        }
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

  const agentExecutionBody = (
    <div className="space-y-4">
      {/* Model */}
      <div className="space-y-1">
        <label className="text-xs font-medium text-[#8a8578]">Model</label>
        <Input
          value={form.model ?? ""}
          onChange={(e) => update("model", e.target.value || undefined)}
          placeholder="Use agent default"
          className="h-8 text-sm font-mono"
        />
      </div>

      {/* Fallbacks */}
      <div className="space-y-1">
        <label className="text-xs font-medium text-[#8a8578]">Fallbacks</label>
        <FallbackModelList
          value={form.fallbacks}
          onChange={(next) => update("fallbacks", next)}
        />
      </div>

      {/* Timeout + Thinking */}
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1">
          <label className="text-xs font-medium text-[#8a8578]">
            Timeout (seconds)
          </label>
          <Input
            type="number"
            min={1}
            value={form.timeoutSeconds ?? ""}
            onChange={(e) => {
              const v = e.target.value;
              if (v === "") return update("timeoutSeconds", undefined);
              const n = Number(v);
              update("timeoutSeconds", Number.isFinite(n) && n > 0 ? n : undefined);
            }}
            placeholder="default"
            className="h-8 text-sm"
          />
        </div>
        <div className="space-y-1">
          <label
            className="text-xs font-medium text-[#8a8578]"
            title="Reasoning/thinking hint passed to the model (provider-specific)."
          >
            Thinking
          </label>
          <Input
            value={form.thinking ?? ""}
            onChange={(e) => update("thinking", e.target.value || undefined)}
            placeholder="e.g. high"
            className="h-8 text-sm"
          />
        </div>
      </div>

      {/* Light context */}
      <div className="space-y-1">
        <label className="flex items-center gap-2 cursor-pointer">
          <Checkbox
            checked={!!form.lightContext}
            onCheckedChange={(checked) =>
              update("lightContext", checked === true)
            }
          />
          <span className="text-sm">Light context</span>
        </label>
        <p className="text-xs text-[#8a8578] pl-6">
          Skip loading recent history for faster/cheaper runs.
        </p>
      </div>

      {/* Tools allowlist */}
      <div className="space-y-1">
        <label className="text-xs font-medium text-[#8a8578]">Tools allowed</label>
        <ToolsAllowlist
          agentId={form.agentId}
          value={form.toolsAllow}
          onChange={(v) => update("toolsAllow", v)}
        />
      </div>
    </div>
  );

  const sections: JobEditSection[] = [
    { id: "basics", title: "Basics", defaultOpen: true, children: basicsBody },
    { id: "delivery", title: "Delivery", defaultOpen: true, children: deliveryBody },
    { id: "agent-execution", title: "Agent execution", defaultOpen: false, children: agentExecutionBody },
    {
      id: "failure-alerts",
      title: "Failure alerts",
      defaultOpen: false,
      children: <FailureAlertsSection form={form} update={update} />,
    },
    {
      id: "advanced",
      title: "Advanced",
      defaultOpen: false,
      children: <AdvancedSection form={form} update={update} />,
    },
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
