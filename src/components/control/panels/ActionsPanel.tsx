"use client";

import { useState, useCallback } from "react";
import {
  Loader2,
  RefreshCw,
  ShieldCheck,
  ShieldX,
  UserCheck,
  UserX,
  RotateCcw,
  Download,
  Activity,
  Radio,
  Trash2,
  AlertCircle,
  CheckCircle2,
} from "lucide-react";
import { useGatewayRpc, useGatewayRpcMutation } from "@/hooks/useGatewayRpc";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/* ── Types ─────────────────────────────────────────────── */

interface PairingRequest {
  id: string;
  code: string;
  channel?: string;
  createdAt?: string;
  lastSeenAt?: string;
  meta?: {
    username?: string;
    firstName?: string;
    lastName?: string;
    accountId?: string;
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

interface PairingListResponse {
  requests?: PairingRequest[];
  [key: string]: unknown;
}

interface StatusResponse {
  version?: string;
  uptime?: number;
  pid?: number;
  platform?: string;
  nodeVersion?: string;
  [key: string]: unknown;
}

/* ── Helpers ───────────────────────────────────────────── */

function formatRelativeTime(iso: string | undefined): string {
  if (!iso) return "n/a";
  const diff = Date.now() - new Date(iso).getTime();
  if (diff < 0) return "just now";
  const secs = Math.floor(diff / 1000);
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function pairingDisplayName(req: PairingRequest): string {
  const meta = req.meta;
  if (!meta) return req.id;
  const parts: string[] = [];
  if (meta.firstName) parts.push(meta.firstName);
  if (meta.lastName) parts.push(meta.lastName);
  if (parts.length > 0) return parts.join(" ");
  if (meta.username) return `@${meta.username}`;
  return req.id;
}

/* ── Component ─────────────────────────────────────────── */

export function ActionsPanel() {
  const callRpc = useGatewayRpcMutation();

  // Pairing requests
  const {
    data: pairingData,
    error: pairingError,
    isLoading: pairingLoading,
    mutate: mutatePairing,
  } = useGatewayRpc<PairingListResponse>("device.pair.list");

  // Gateway status
  const {
    data: statusData,
    error: statusError,
    isLoading: statusLoading,
    mutate: mutateStatus,
  } = useGatewayRpc<StatusResponse>("status");

  // Action feedback
  const [busy, setBusy] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; message: string } | null>(null);

  const clearFeedback = () => setFeedback(null);

  const runAction = useCallback(
    async (label: string, method: string, params?: Record<string, unknown>, postAction?: () => void) => {
      setBusy(label);
      setFeedback(null);
      try {
        await callRpc(method, params);
        setFeedback({ type: "success", message: `${label}: success` });
        postAction?.();
      } catch (err) {
        setFeedback({
          type: "error",
          message: `${label}: ${err instanceof Error ? err.message : String(err)}`,
        });
      } finally {
        setBusy(null);
      }
    },
    [callRpc],
  );

  const requests = pairingData?.requests ?? [];

  return (
    <div className="p-6 space-y-6 overflow-auto">
      {/* Header */}
      <div>
        <h2 className="text-lg font-semibold">Actions</h2>
        <p className="text-xs text-muted-foreground">
          Gateway commands and device pairing.
        </p>
      </div>

      {/* Feedback banner */}
      {feedback && (
        <div
          className={cn(
            "flex items-center gap-2 rounded-md border p-3 text-xs",
            feedback.type === "success"
              ? "border-emerald-500/30 bg-emerald-500/5 text-emerald-400"
              : "border-destructive/30 bg-destructive/5 text-destructive",
          )}
        >
          {feedback.type === "success" ? (
            <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
          ) : (
            <AlertCircle className="h-3.5 w-3.5 shrink-0" />
          )}
          <span className="flex-1">{feedback.message}</span>
          <button
            className="text-muted-foreground hover:text-foreground"
            onClick={clearFeedback}
          >
            dismiss
          </button>
        </div>
      )}

      {/* ── Device Pairing ──────────────────────────────── */}
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-muted-foreground" />
            <h3 className="text-sm font-semibold">Device Pairing</h3>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => mutatePairing()}
            disabled={pairingLoading}
          >
            {pairingLoading ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" />
            )}
          </Button>
        </div>

        {pairingError && (
          <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-xs text-destructive">
            {pairingError.message}
          </div>
        )}

        {pairingLoading && !pairingData ? (
          <div className="flex items-center justify-center py-4">
            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
          </div>
        ) : requests.length === 0 ? (
          <p className="text-xs text-muted-foreground rounded-md border border-border/50 bg-muted/10 p-3">
            No pending pairing requests. When someone messages your bot for the first time,
            their request will appear here for approval.
          </p>
        ) : (
          <div className="space-y-2">
            {requests.map((req) => (
              <div
                key={req.code}
                className="rounded-lg border border-border p-3 space-y-2"
              >
                <div className="flex items-center justify-between">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium truncate">
                        {pairingDisplayName(req)}
                      </span>
                      {req.meta?.username && (
                        <span className="text-xs text-muted-foreground">
                          @{req.meta.username}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-3 text-[11px] text-muted-foreground mt-0.5">
                      {req.channel && (
                        <span className="inline-flex items-center gap-1">
                          <Radio className="h-3 w-3" />
                          {req.channel}
                        </span>
                      )}
                      <span>ID: {req.id}</span>
                      <span>Code: <code className="font-mono bg-muted/30 px-1 rounded">{req.code}</code></span>
                      <span>{formatRelativeTime(req.createdAt)}</span>
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <Button
                    variant="default"
                    size="sm"
                    className="h-7 text-xs bg-emerald-600 hover:bg-emerald-700"
                    disabled={busy !== null}
                    onClick={() =>
                      runAction("Approve", "device.pair.approve", { code: req.code }, () =>
                        mutatePairing(),
                      )
                    }
                  >
                    {busy === "Approve" ? (
                      <Loader2 className="h-3 w-3 animate-spin mr-1" />
                    ) : (
                      <UserCheck className="h-3 w-3 mr-1" />
                    )}
                    Approve
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-7 text-xs text-destructive hover:bg-destructive/10"
                    disabled={busy !== null}
                    onClick={() =>
                      runAction("Reject", "device.pair.reject", { code: req.code }, () =>
                        mutatePairing(),
                      )
                    }
                  >
                    {busy === "Reject" ? (
                      <Loader2 className="h-3 w-3 animate-spin mr-1" />
                    ) : (
                      <UserX className="h-3 w-3 mr-1" />
                    )}
                    Reject
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* ── Gateway Commands ────────────────────────────── */}
      <section className="space-y-3">
        <div className="flex items-center gap-2">
          <Activity className="h-4 w-4 text-muted-foreground" />
          <h3 className="text-sm font-semibold">Gateway</h3>
        </div>

        {statusError && (
          <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-xs text-destructive">
            {statusError.message}
          </div>
        )}

        {/* Status summary */}
        {statusData && (
          <div className="rounded-md border border-border/50 bg-muted/10 p-3">
            <div className="grid grid-cols-2 md:grid-cols-3 gap-x-4 gap-y-1 text-xs">
              {statusData.version && (
                <div>
                  <span className="text-muted-foreground">Version: </span>
                  <span className="font-medium">{statusData.version}</span>
                </div>
              )}
              {statusData.uptime != null && (
                <div>
                  <span className="text-muted-foreground">Uptime: </span>
                  <span className="font-medium">
                    {Math.floor(statusData.uptime / 60)}m
                  </span>
                </div>
              )}
              {statusData.platform && (
                <div>
                  <span className="text-muted-foreground">Platform: </span>
                  <span className="font-medium">{statusData.platform}</span>
                </div>
              )}
              {statusData.nodeVersion && (
                <div>
                  <span className="text-muted-foreground">Node: </span>
                  <span className="font-medium">{statusData.nodeVersion}</span>
                </div>
              )}
              {statusData.pid != null && (
                <div>
                  <span className="text-muted-foreground">PID: </span>
                  <span className="font-mono font-medium">{statusData.pid}</span>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Action buttons */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <ActionButton
            icon={RefreshCw}
            label="Reload Config"
            description="Re-read config and restart channels"
            busy={busy}
            busyKey="Reload Config"
            onClick={() =>
              runAction("Reload Config", "config.apply", {}, () => {
                mutateStatus();
              })
            }
          />
          <ActionButton
            icon={Download}
            label="Update Gateway"
            description="Pull latest version and restart"
            busy={busy}
            busyKey="Update Gateway"
            variant="warning"
            onClick={() => {
              if (!window.confirm("Update gateway? This will restart the service.")) return;
              runAction("Update Gateway", "update.run", {}, () => {
                setTimeout(() => mutateStatus(), 5000);
              });
            }}
          />
          <ActionButton
            icon={Radio}
            label="Probe Channels"
            description="Check all channel connections"
            busy={busy}
            busyKey="Probe Channels"
            onClick={() =>
              runAction("Probe Channels", "channels.status", { probe: true, timeoutMs: 8000 })
            }
          />
          <ActionButton
            icon={Activity}
            label="Health Check"
            description="Verify gateway is responsive"
            busy={busy}
            busyKey="Health Check"
            onClick={() => runAction("Health Check", "health", {}, () => mutateStatus())}
          />
          <ActionButton
            icon={RotateCcw}
            label="Reset Sessions"
            description="Clear all active sessions"
            busy={busy}
            busyKey="Reset Sessions"
            variant="danger"
            onClick={() => {
              if (!window.confirm("Reset all sessions? This cannot be undone.")) return;
              runAction("Reset Sessions", "sessions.reset", {});
            }}
          />
          <ActionButton
            icon={Trash2}
            label="Clear Cron Runs"
            description="Reset cron run history"
            busy={busy}
            busyKey="Clear Cron Runs"
            onClick={() => runAction("Clear Cron Runs", "cron.runs", { clear: true })}
          />
        </div>
      </section>

      {/* Raw status for debugging */}
      {statusData && (
        <details className="text-xs">
          <summary className="text-muted-foreground cursor-pointer hover:text-foreground">
            Raw gateway status
          </summary>
          <pre className="mt-2 p-3 rounded-md bg-muted/30 border border-border/40 overflow-auto max-h-60 text-[10px] leading-tight">
            {JSON.stringify(statusData, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}

/* ── Action Button ───────────────────────────────────── */

function ActionButton({
  icon: Icon,
  label,
  description,
  busy,
  busyKey,
  variant,
  onClick,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  description: string;
  busy: string | null;
  busyKey: string;
  variant?: "warning" | "danger";
  onClick: () => void;
}) {
  const isBusy = busy === busyKey;

  return (
    <button
      className={cn(
        "flex items-start gap-3 rounded-lg border p-3 text-left transition-colors",
        "hover:bg-accent/50 disabled:opacity-50 disabled:cursor-not-allowed",
        variant === "danger" && "border-destructive/20 hover:border-destructive/40",
        variant === "warning" && "border-amber-500/20 hover:border-amber-500/40",
        !variant && "border-border",
      )}
      disabled={busy !== null}
      onClick={onClick}
    >
      {isBusy ? (
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground mt-0.5 shrink-0" />
      ) : (
        <Icon
          className={cn(
            "h-4 w-4 mt-0.5 shrink-0",
            variant === "danger" && "text-destructive",
            variant === "warning" && "text-amber-500",
            !variant && "text-muted-foreground",
          )}
        />
      )}
      <div className="min-w-0">
        <div className="text-xs font-medium">{label}</div>
        <div className="text-[10px] text-muted-foreground leading-snug">{description}</div>
      </div>
    </button>
  );
}
