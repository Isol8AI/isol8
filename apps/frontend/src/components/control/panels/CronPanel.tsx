"use client";

import { useState, useCallback, useMemo } from "react";
import cronstrue from "cronstrue";
import {
  Loader2,
  RefreshCw,
  X,
} from "lucide-react";
import { useGatewayRpc, useGatewayRpcMutation } from "@/hooks/useGatewayRpc";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { JobList } from "./cron/JobList";
import type {
  CronJob,
  CronListResponse,
  CronSchedule,
  CronScheduleKind,
} from "./cron/types";

// --- Form-local types (retained here pending Task 11 refactor) ---

type ScheduleKind = CronScheduleKind;

interface FormState {
  name: string;
  scheduleKind: ScheduleKind;
  cronExpr: string;
  cronTz: string;
  everyValue: number;
  everyUnit: "minutes" | "hours" | "days";
  atDatetime: string;
  message: string;
  enabled: boolean;
}

const EMPTY_FORM: FormState = {
  name: "",
  scheduleKind: "cron",
  cronExpr: "",
  cronTz: "",
  everyValue: 30,
  everyUnit: "minutes",
  atDatetime: "",
  message: "",
  enabled: true,
};

// --- Helpers ---

function buildSchedule(form: FormState): CronSchedule {
  switch (form.scheduleKind) {
    case "cron":
      return { kind: "cron", expr: form.cronExpr, ...(form.cronTz ? { tz: form.cronTz } : {}) };
    case "every": {
      const multipliers = { minutes: 60000, hours: 3600000, days: 86400000 };
      return { kind: "every", everyMs: form.everyValue * multipliers[form.everyUnit] };
    }
    case "at":
      return { kind: "at", at: new Date(form.atDatetime).toISOString() };
  }
}

function jobToForm(job: CronJob): FormState {
  const s = job.schedule;
  const msg = job.payload?.kind === "agentTurn" ? (job.payload.message ?? "") : (job.payload?.text ?? "");
  const base = { name: job.name, message: msg, enabled: job.enabled };
  if (s.kind === "cron") {
    return { ...EMPTY_FORM, ...base, scheduleKind: "cron", cronExpr: s.expr ?? "", cronTz: s.tz ?? "" };
  }
  if (s.kind === "every") {
    const ms = s.everyMs ?? 60000;
    if (ms >= 86400000) return { ...EMPTY_FORM, ...base, scheduleKind: "every", everyValue: Math.round(ms / 86400000), everyUnit: "days" };
    if (ms >= 3600000) return { ...EMPTY_FORM, ...base, scheduleKind: "every", everyValue: Math.round(ms / 3600000), everyUnit: "hours" };
    return { ...EMPTY_FORM, ...base, scheduleKind: "every", everyValue: Math.round(ms / 60000), everyUnit: "minutes" };
  }
  if (s.kind === "at") {
    let atDatetime = "";
    try {
      atDatetime = s.at ? new Date(s.at).toISOString().slice(0, 16) : "";
    } catch { /* ignore */ }
    return { ...EMPTY_FORM, ...base, scheduleKind: "at", atDatetime };
  }
  return { ...EMPTY_FORM, ...base };
}

// --- Create/Edit form ---

function CronJobForm({
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

  const cronValidation = useMemo<{ ok: boolean; description?: string; error?: string }>(() => {
    const expr = form.cronExpr.trim();
    if (!expr) return { ok: false };
    try {
      const description = cronstrue.toString(expr, { throwExceptionOnParseError: true });
      return { ok: true, description };
    } catch (e) {
      return { ok: false, error: e instanceof Error ? e.message : "Invalid cron expression" };
    }
  }, [form.cronExpr]);

  const canSubmit = form.name.trim() && form.message.trim() && (
    (form.scheduleKind === "cron" && cronValidation.ok) ||
    (form.scheduleKind === "every" && form.everyValue > 0) ||
    (form.scheduleKind === "at" && form.atDatetime)
  );

  return (
    <div className="rounded-lg border border-[#e0dbd0] p-4 space-y-4 bg-white/80">
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

      {/* Schedule type selector */}
      <div className="space-y-2">
        <label className="text-xs font-medium text-[#8a8578]">Schedule</label>
        <div className="flex gap-1">
          {(["cron", "every", "at"] as const).map((kind) => (
            <Button
              key={kind}
              variant={form.scheduleKind === kind ? "default" : "outline"}
              size="sm"
              onClick={() => update("scheduleKind", kind)}
              className="text-xs"
            >
              {kind === "cron" ? "Cron Expression" : kind === "every" ? "Interval" : "One-time"}
            </Button>
          ))}
        </div>

        {form.scheduleKind === "cron" && (
          <div className="space-y-1.5">
            <div className="flex gap-2">
              <Input
                value={form.cronExpr}
                onChange={(e) => update("cronExpr", e.target.value)}
                placeholder="0 9 * * *"
                className={cn(
                  "h-8 text-sm font-mono flex-1",
                  form.cronExpr.trim() && !cronValidation.ok && "border-destructive focus-visible:ring-destructive",
                )}
              />
              <Input
                value={form.cronTz}
                onChange={(e) => update("cronTz", e.target.value)}
                placeholder="Timezone (optional)"
                className="h-8 text-sm w-40"
              />
            </div>
            {form.cronExpr.trim() && (
              cronValidation.ok ? (
                <p className="text-xs text-[#2d8a4e]">{cronValidation.description}</p>
              ) : (
                <p className="text-xs text-destructive">{cronValidation.error}</p>
              )
            )}
          </div>
        )}

        {form.scheduleKind === "every" && (
          <div className="flex gap-2 items-center">
            <span className="text-sm text-[#8a8578]">Every</span>
            <Input
              type="number"
              min={1}
              value={form.everyValue}
              onChange={(e) => update("everyValue", Math.max(1, parseInt(e.target.value) || 1))}
              className="h-8 text-sm w-20"
            />
            <select
              value={form.everyUnit}
              onChange={(e) => update("everyUnit", e.target.value as "minutes" | "hours" | "days")}
              className="h-8 rounded-md border border-[#e0dbd0] bg-[#faf7f2] px-2 text-sm"
            >
              <option value="minutes">minutes</option>
              <option value="hours">hours</option>
              <option value="days">days</option>
            </select>
          </div>
        )}

        {form.scheduleKind === "at" && (
          <Input
            type="datetime-local"
            value={form.atDatetime}
            onChange={(e) => update("atDatetime", e.target.value)}
            className="h-8 text-sm"
          />
        )}
      </div>

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

// --- Main panel ---

export function CronPanel() {
  const { data, error, isLoading, mutate } = useGatewayRpc<CronListResponse>("cron.list", {
    includeDisabled: true,
  });
  const callRpc = useGatewayRpcMutation();

  const [mode, setMode] = useState<"list" | "create" | "edit">("list");
  const [editingJob, setEditingJob] = useState<CronJob | null>(null);
  const [expandedJob, setExpandedJob] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; message: string } | null>(null);

  const showFeedback = useCallback((type: "success" | "error", message: string) => {
    setFeedback({ type, message });
    setTimeout(() => setFeedback(null), 3000);
  }, []);

  const handleCreate = async (form: FormState) => {
    setSaving(true);
    try {
      await callRpc("cron.add", {
        name: form.name.trim(),
        schedule: buildSchedule(form),
        payload: { kind: "agentTurn", message: form.message.trim() },
        enabled: form.enabled,
        sessionTarget: "isolated",
        wakeMode: "now",
      });
      setMode("list");
      mutate();
      showFeedback("success", `Created "${form.name.trim()}"`);
    } catch (err) {
      showFeedback("error", `Failed to create: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setSaving(false);
    }
  };

  const handleEdit = async (form: FormState) => {
    if (!editingJob) return;
    setSaving(true);
    try {
      await callRpc("cron.update", {
        id: editingJob.id,
        patch: {
          name: form.name.trim(),
          schedule: buildSchedule(form),
          payload: { kind: "agentTurn", message: form.message.trim() },
          enabled: form.enabled,
        },
      });
      setMode("list");
      setEditingJob(null);
      mutate();
      showFeedback("success", `Updated "${form.name.trim()}"`);
    } catch (err) {
      showFeedback("error", `Failed to update: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await callRpc("cron.remove", { id });
      mutate();
      showFeedback("success", "Job deleted");
    } catch (err) {
      showFeedback("error", `Failed to delete: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const handleToggle = async (id: string, currentlyEnabled: boolean) => {
    try {
      await callRpc("cron.update", { id, patch: { enabled: !currentlyEnabled } });
      mutate();
    } catch (err) {
      showFeedback("error", `Failed to toggle: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const handleRun = async (id: string) => {
    try {
      await callRpc("cron.run", { id, mode: "force" });
      showFeedback("success", "Job triggered");
      mutate();
    } catch (err) {
      showFeedback("error", `Failed to run: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  // Loading state
  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-[#8a8578]" />
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="p-6 space-y-3">
        <p className="text-sm text-destructive">{error.message}</p>
        <Button variant="outline" size="sm" onClick={() => mutate()}>
          <RefreshCw className="h-3.5 w-3.5 mr-1.5" /> Retry
        </Button>
      </div>
    );
  }

  const jobs = data?.jobs ?? (Array.isArray(data) ? (data as unknown as CronJob[]) : []);

  return (
    <div className="p-6 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Cron Jobs</h2>
        <div className="flex gap-1">
          <Button variant="ghost" size="sm" onClick={() => mutate()}>
            <RefreshCw className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {/* Feedback banner */}
      {feedback && (
        <div
          className={cn(
            "flex items-center justify-between rounded-md px-3 py-2 text-sm",
            feedback.type === "success"
              ? "bg-[#e8f5e9] text-[#2d8a4e] border border-[#2d8a4e]/20"
              : "bg-destructive/10 text-destructive border border-destructive/20",
          )}
        >
          <span>{feedback.message}</span>
          <button onClick={() => setFeedback(null)} className="opacity-60 hover:opacity-100">
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      {/* Create form */}
      {mode === "create" && (
        <CronJobForm
          initial={EMPTY_FORM}
          onSave={handleCreate}
          onCancel={() => setMode("list")}
          saving={saving}
        />
      )}

      {/* Edit form */}
      {mode === "edit" && editingJob && (
        <CronJobForm
          initial={jobToForm(editingJob)}
          onSave={handleEdit}
          onCancel={() => {
            setMode("list");
            setEditingJob(null);
          }}
          saving={saving}
        />
      )}

      {/* Job list */}
      {mode === "list" && (
        <JobList
          jobs={jobs}
          expandedJobId={expandedJob}
          onToggleExpand={(jobId) =>
            setExpandedJob(expandedJob === jobId ? null : jobId)
          }
          onCreate={() => setMode("create")}
          onEdit={(job) => {
            setEditingJob(job);
            setMode("edit");
          }}
          onPauseResume={(job) => handleToggle(job.id, !!job.enabled)}
          onRunNow={(job) => handleRun(job.id)}
          onDelete={(job) => handleDelete(job.id)}
          onSelectRun={() => {
            /* no-op for now; Task 7 wires this */
          }}
        />
      )}
    </div>
  );
}
