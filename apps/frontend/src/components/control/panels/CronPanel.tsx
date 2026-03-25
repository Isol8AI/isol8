"use client";

import { useState, useCallback } from "react";
import {
  Loader2,
  RefreshCw,
  Clock,
  Play,
  Plus,
  Pencil,
  Trash2,
  ChevronDown,
  ChevronRight,
  CheckCircle2,
  XCircle,
  MinusCircle,
  X,
} from "lucide-react";
import { useGatewayRpc, useGatewayRpcMutation } from "@/hooks/useGatewayRpc";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

// --- Types ---

interface CronSchedule {
  kind: "cron" | "every" | "at";
  expr?: string;
  tz?: string;
  everyMs?: number;
  at?: string;
}

interface CronPayload {
  kind: "agentTurn" | "systemEvent";
  message?: string;
  text?: string;
}

interface CronJobState {
  lastRunAtMs?: number;
  lastRunStatus?: "ok" | "error" | "skipped";
  lastError?: string;
  lastDurationMs?: number;
  nextRunAtMs?: number;
}

interface CronJob {
  id: string;
  name: string;
  description?: string;
  enabled: boolean;
  agentId?: string;
  schedule: CronSchedule;
  payload?: CronPayload;
  state?: CronJobState;
  createdAtMs?: number;
  updatedAtMs?: number;
}

interface CronListResponse {
  jobs?: CronJob[];
  total?: number;
  hasMore?: boolean;
}

interface CronRunEntry {
  jobId: string;
  jobName?: string;
  triggeredAtMs: number;
  completedAtMs?: number;
  status: "ok" | "error" | "skipped";
  error?: string;
  summary?: string;
  durationMs?: number;
}

interface CronRunsResponse {
  entries?: CronRunEntry[];
  total?: number;
  hasMore?: boolean;
}

type ScheduleKind = "cron" | "every" | "at";

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

function formatSchedule(schedule: CronSchedule): string {
  if (!schedule || !schedule.kind) return "\u2014";
  switch (schedule.kind) {
    case "cron":
      return schedule.expr ? `cron: ${schedule.expr}${schedule.tz ? ` (${schedule.tz})` : ""}` : "\u2014";
    case "every": {
      if (!schedule.everyMs) return "\u2014";
      const ms = schedule.everyMs;
      if (ms >= 86400000) return `Every ${Math.round(ms / 86400000)} day${ms >= 172800000 ? "s" : ""}`;
      if (ms >= 3600000) return `Every ${Math.round(ms / 3600000)} hour${ms >= 7200000 ? "s" : ""}`;
      return `Every ${Math.round(ms / 60000)} minute${ms >= 120000 ? "s" : ""}`;
    }
    case "at":
      if (!schedule.at) return "\u2014";
      try {
        return `Once at ${new Date(schedule.at).toLocaleString()}`;
      } catch {
        return `Once at ${schedule.at}`;
      }
    default:
      return JSON.stringify(schedule);
  }
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.round(ms / 60000)}m`;
}

function formatTimestamp(ms: number): string {
  try {
    return new Date(ms).toLocaleString();
  } catch {
    return String(ms);
  }
}

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

// --- Status badge ---

function StatusBadge({ status }: { status?: "ok" | "error" | "skipped" }) {
  if (!status) return null;
  const config = {
    ok: { icon: CheckCircle2, label: "OK", className: "text-green-500" },
    error: { icon: XCircle, label: "Error", className: "text-red-500" },
    skipped: { icon: MinusCircle, label: "Skipped", className: "text-yellow-500" },
  };
  const { icon: Icon, label, className } = config[status];
  return (
    <span className={cn("inline-flex items-center gap-1 text-xs", className)}>
      <Icon className="h-3 w-3" />
      {label}
    </span>
  );
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

  const canSubmit = form.name.trim() && form.message.trim() && (
    (form.scheduleKind === "cron" && form.cronExpr.trim()) ||
    (form.scheduleKind === "every" && form.everyValue > 0) ||
    (form.scheduleKind === "at" && form.atDatetime)
  );

  return (
    <div className="rounded-lg border border-border p-4 space-y-4 bg-muted/30">
      {/* Name */}
      <div className="space-y-1">
        <label className="text-xs font-medium text-muted-foreground">Name</label>
        <Input
          value={form.name}
          onChange={(e) => update("name", e.target.value)}
          placeholder="e.g. Daily summary"
          className="h-8 text-sm"
        />
      </div>

      {/* Schedule type selector */}
      <div className="space-y-2">
        <label className="text-xs font-medium text-muted-foreground">Schedule</label>
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
          <div className="flex gap-2">
            <Input
              value={form.cronExpr}
              onChange={(e) => update("cronExpr", e.target.value)}
              placeholder="0 9 * * *"
              className="h-8 text-sm font-mono flex-1"
            />
            <Input
              value={form.cronTz}
              onChange={(e) => update("cronTz", e.target.value)}
              placeholder="Timezone (optional)"
              className="h-8 text-sm w-40"
            />
          </div>
        )}

        {form.scheduleKind === "every" && (
          <div className="flex gap-2 items-center">
            <span className="text-sm text-muted-foreground">Every</span>
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
              className="h-8 rounded-md border border-input bg-background px-2 text-sm"
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
        <label className="text-xs font-medium text-muted-foreground">Agent message</label>
        <textarea
          value={form.message}
          onChange={(e) => update("message", e.target.value)}
          placeholder="What should the agent do?"
          rows={3}
          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm resize-none focus:outline-none focus:ring-1 focus:ring-ring"
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

// --- Run history ---

function RunHistory({ jobId }: { jobId: string }) {
  const { data, error, isLoading } = useGatewayRpc<CronRunsResponse>("cron.runs", {
    scope: "job",
    id: jobId,
    limit: 10,
    sortDir: "desc",
  });

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 py-2 text-xs text-muted-foreground">
        <Loader2 className="h-3 w-3 animate-spin" /> Loading history...
      </div>
    );
  }

  if (error) {
    return <p className="text-xs text-destructive py-1">Failed to load history</p>;
  }

  const entries = data?.entries ?? [];
  if (entries.length === 0) {
    return <p className="text-xs text-muted-foreground py-1">No runs yet</p>;
  }

  return (
    <div className="space-y-1">
      {entries.map((entry, i) => (
        <div key={i} className="flex items-center gap-3 text-xs py-1 border-t border-border/50">
          <StatusBadge status={entry.status} />
          <span className="text-muted-foreground">{formatTimestamp(entry.triggeredAtMs)}</span>
          {entry.durationMs != null && (
            <span className="text-muted-foreground">{formatDuration(entry.durationMs)}</span>
          )}
          {entry.summary && (
            <span className="text-muted-foreground/70 truncate flex-1">{entry.summary}</span>
          )}
          {entry.error && (
            <span className="text-destructive truncate flex-1">{entry.error}</span>
          )}
        </div>
      ))}
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
  const [deletingJob, setDeletingJob] = useState<string | null>(null);
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
      setDeletingJob(null);
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
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
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
          {mode === "list" && (
            <Button size="sm" onClick={() => setMode("create")}>
              <Plus className="h-3.5 w-3.5 mr-1.5" /> New Job
            </Button>
          )}
        </div>
      </div>

      {/* Feedback banner */}
      {feedback && (
        <div
          className={cn(
            "flex items-center justify-between rounded-md px-3 py-2 text-sm",
            feedback.type === "success"
              ? "bg-green-500/10 text-green-500 border border-green-500/20"
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
      {mode === "list" && jobs.length === 0 && (
        <div className="text-center py-8 space-y-2">
          <Clock className="h-8 w-8 mx-auto opacity-30" />
          <p className="text-sm text-muted-foreground">No cron jobs configured.</p>
          <p className="text-xs text-muted-foreground/70">Create a job to schedule recurring agent tasks.</p>
        </div>
      )}

      {mode === "list" && jobs.length > 0 && (
        <div className="space-y-2">
          {jobs.map((job) => {
            const isExpanded = expandedJob === job.id;
            const isDeleting = deletingJob === job.id;

            return (
              <div key={job.id} className="rounded-lg border border-border overflow-hidden">
                {/* Job header */}
                <div className="p-3 space-y-2">
                  <div className="flex items-center justify-between">
                    <button
                      className="flex items-center gap-2 text-left flex-1 min-w-0"
                      onClick={() => setExpandedJob(isExpanded ? null : job.id)}
                    >
                      {isExpanded ? (
                        <ChevronDown className="h-3.5 w-3.5 opacity-50 shrink-0" />
                      ) : (
                        <ChevronRight className="h-3.5 w-3.5 opacity-50 shrink-0" />
                      )}
                      <Clock className="h-3.5 w-3.5 opacity-50 shrink-0" />
                      <span className="text-sm font-medium truncate">{job.name || job.id}</span>
                      <span
                        className={cn(
                          "text-[10px] px-1.5 py-0.5 rounded-full shrink-0",
                          job.enabled
                            ? "bg-green-500/10 text-green-500"
                            : "bg-muted text-muted-foreground",
                        )}
                      >
                        {job.enabled ? "active" : "paused"}
                      </span>
                    </button>
                    <div className="flex gap-1 shrink-0">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleRun(job.id)}
                        title="Run now"
                      >
                        <Play className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => {
                          setEditingJob(job);
                          setMode("edit");
                        }}
                        title="Edit"
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        variant={job.enabled ? "outline" : "default"}
                        size="sm"
                        onClick={() => handleToggle(job.id, !!job.enabled)}
                      >
                        {job.enabled ? "Disable" : "Enable"}
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setDeletingJob(isDeleting ? null : job.id)}
                        title="Delete"
                        className="text-destructive/70 hover:text-destructive"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </div>

                  {/* Schedule + last run info */}
                  <div className="flex items-center gap-3 text-xs text-muted-foreground pl-7">
                    <span>{formatSchedule(job.schedule)}</span>
                    {job.state?.lastRunStatus && (
                      <>
                        <span>&middot;</span>
                        <StatusBadge status={job.state.lastRunStatus} />
                      </>
                    )}
                    {job.state?.nextRunAtMs && (
                      <>
                        <span>&middot;</span>
                        <span>Next: {formatTimestamp(job.state.nextRunAtMs)}</span>
                      </>
                    )}
                  </div>

                  {job.description && (
                    <div className="text-xs text-muted-foreground/70 pl-7">{job.description}</div>
                  )}
                </div>

                {/* Delete confirmation */}
                {isDeleting && (
                  <div className="px-3 pb-3">
                    <div className="flex items-center justify-between rounded-md bg-destructive/10 border border-destructive/20 px-3 py-2">
                      <span className="text-sm text-destructive">
                        Delete &ldquo;{job.name || job.id}&rdquo;? This cannot be undone.
                      </span>
                      <div className="flex gap-1">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setDeletingJob(null)}
                        >
                          Cancel
                        </Button>
                        <Button
                          variant="destructive"
                          size="sm"
                          onClick={() => handleDelete(job.id)}
                        >
                          Delete
                        </Button>
                      </div>
                    </div>
                  </div>
                )}

                {/* Expanded: run history */}
                {isExpanded && (
                  <div className="px-3 pb-3 pl-7 border-t border-border/50">
                    <p className="text-xs font-medium text-muted-foreground pt-2 pb-1">Run History</p>
                    <RunHistory jobId={job.id} />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
