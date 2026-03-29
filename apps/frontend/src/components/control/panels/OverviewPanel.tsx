"use client";

import { useState, useCallback } from "react";
import {
  Loader2,
  RefreshCw,
  Wifi,
  WifiOff,
  Clock,
  Server,
  MessageSquare,
  Users,
  Timer,
  MapPin,
  CreditCard,
  Activity,
  RotateCcw,
  Download,
  Radio,
  AlertCircle,
  CheckCircle2,
} from "lucide-react";
import { useGatewayRpc, useGatewayRpcMutation } from "@/hooks/useGatewayRpc";
import { useContainerStatus } from "@/hooks/useContainerStatus";
import { useBilling } from "@/hooks/useBilling";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface HealthAgent {
  agentId?: string;
  isDefault?: boolean;
  sessions?: { count?: number; recent?: unknown[] };
  [key: string]: unknown;
}

interface HealthPayload {
  ok?: boolean;
  ts?: number;
  durationMs?: number;
  channels?: Record<string, unknown>;
  heartbeatSeconds?: number;
  defaultAgentId?: string;
  agents?: HealthAgent[];
  sessions?: { count?: number; recent?: unknown[] };
  tickInterval?: number;
  lastChannelsRefresh?: number;
  [key: string]: unknown;
}

interface HealthResponse {
  type?: string;
  event?: string;
  payload?: HealthPayload;
  [key: string]: unknown;
}

interface CronJob {
  name?: string;
  enabled?: boolean;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function extractHealth(data: HealthResponse): HealthPayload {
  if (data.type === "event" && data.payload) {
    return data.payload;
  }
  return data as HealthPayload;
}

function formatUptime(ts: number | undefined): string {
  if (!ts) return "\u2014";
  const uptimeMs = Date.now() - ts;
  if (uptimeMs < 0) return "\u2014";
  const seconds = Math.floor(uptimeMs / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  if (hours > 24) return `${Math.floor(hours / 24)}d ${hours % 24}h`;
  if (hours > 0) return `${hours}h ${minutes % 60}m`;
  return `${minutes}m`;
}

function formatTimeAgo(ts: number | string | undefined | null): string {
  if (!ts) return "\u2014";
  const ms = typeof ts === "string" ? new Date(ts).getTime() : ts;
  const ago = Date.now() - ms;
  if (ago < 0) return "\u2014";
  const minutes = Math.floor(ago / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function OverviewPanel() {
  const {
    data: rawHealth,
    error: healthError,
    isLoading: healthLoading,
    mutate: refreshHealth,
  } = useGatewayRpc<HealthResponse>("health", undefined, { refreshInterval: 10000 });

  const { container, isLoading: statusLoading, error: statusError } = useContainerStatus();
  const { planTier } = useBilling();

  const { data: cronData } = useGatewayRpc<CronJob[]>("cron.list");

  const isLoading = healthLoading && statusLoading;
  const error = healthError || statusError;

  const handleRefresh = () => {
    refreshHealth();
  };

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-[#8a8578]" />
      </div>
    );
  }

  if (error && !rawHealth && !container) {
    return (
      <div className="p-6 space-y-3">
        <p className="text-sm text-destructive">Failed to fetch status: {error.message}</p>
        <Button variant="outline" size="sm" onClick={handleRefresh}>
          <RefreshCw className="h-3.5 w-3.5 mr-1.5" /> Retry
        </Button>
      </div>
    );
  }

  if (!rawHealth && !container) {
    return (
      <div className="p-6 text-sm text-[#8a8578]">No container available.</div>
    );
  }

  const health = rawHealth ? extractHealth(rawHealth) : ({} as HealthPayload);
  const isOnline = health.ok === true;
  const sessionCount = health.sessions?.count;
  const agentCount = health.agents?.length;
  const cronEnabled = Array.isArray(cronData)
    ? cronData.some((j) => j.enabled)
    : false;

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Overview</h2>
          <p className="text-xs text-[#8a8578]">
            Container status and gateway health snapshot.
          </p>
        </div>
        <Button variant="ghost" size="sm" onClick={handleRefresh}>
          <RefreshCw className="h-3.5 w-3.5" />
        </Button>
      </div>

      {/* Two-column: Container Info + Snapshot */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Container Info */}
        <div className="rounded-lg border border-[#e0dbd0] bg-white p-4 space-y-3">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-[#8a8578]">
            Container Info
          </h3>
          <div className="space-y-2">
            <InfoRow
              icon={<Activity className="h-3.5 w-3.5" />}
              label="Status"
              value={container?.status ?? "\u2014"}
              badge={container?.status === "running" ? "green" : container?.status === "provisioning" ? "yellow" : "red"}
            />
            <InfoRow
              icon={<Server className="h-3.5 w-3.5" />}
              label="Service"
              value={container?.service_name ?? "\u2014"}
            />
            <InfoRow
              icon={<CreditCard className="h-3.5 w-3.5" />}
              label="Plan"
              value={planTier}
            />
            <InfoRow
              icon={<MapPin className="h-3.5 w-3.5" />}
              label="Region"
              value={container?.region ?? "\u2014"}
            />
            <InfoRow
              icon={<Clock className="h-3.5 w-3.5" />}
              label="Created"
              value={formatTimeAgo(container?.created_at)}
            />
          </div>
        </div>

        {/* Snapshot */}
        <div className="rounded-lg border border-[#e0dbd0] bg-white p-4 space-y-3">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-[#8a8578]">
            Snapshot
          </h3>
          <div className="space-y-2">
            <InfoRow
              icon={isOnline ? <Wifi className="h-3.5 w-3.5" /> : <WifiOff className="h-3.5 w-3.5" />}
              label="Status"
              value={isOnline ? "OK" : "Offline"}
              badge={isOnline ? "green" : "red"}
            />
            <InfoRow
              icon={<Clock className="h-3.5 w-3.5" />}
              label="Uptime"
              value={formatUptime(health.ts)}
            />
            <InfoRow
              icon={<Timer className="h-3.5 w-3.5" />}
              label="Tick Interval"
              value={
                health.heartbeatSeconds
                  ? `${health.heartbeatSeconds}s`
                  : health.tickInterval
                    ? `${health.tickInterval}s`
                    : "\u2014"
              }
            />
            <InfoRow
              icon={<RefreshCw className="h-3.5 w-3.5" />}
              label="Last Channels"
              value={formatTimeAgo(health.lastChannelsRefresh)}
            />
          </div>
        </div>
      </div>

      {/* Summary Row */}
      <div className="grid grid-cols-3 gap-3">
        <SummaryCard
          icon={Users}
          label="Instances"
          value={agentCount !== undefined ? String(agentCount) : "\u2014"}
        />
        <SummaryCard
          icon={MessageSquare}
          label="Sessions"
          value={sessionCount !== undefined ? String(sessionCount) : "\u2014"}
        />
        <SummaryCard
          icon={Activity}
          label="Cron"
          value={cronEnabled ? "Enabled" : "Disabled"}
        />
      </div>

      {/* Gateway Actions */}
      <GatewayActions onRefresh={handleRefresh} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function InfoRow({
  icon,
  label,
  value,
  badge,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  badge?: "green" | "yellow" | "red";
}) {
  const badgeClass =
    badge === "green"
      ? "text-[#2d8a4e] bg-[#e8f5e9]"
      : badge === "yellow"
        ? "text-yellow-600 bg-yellow-500/10"
        : badge === "red"
          ? "text-red-600 bg-red-500/10"
          : "";

  return (
    <div className="flex items-center justify-between text-sm">
      <div className="flex items-center gap-2 text-[#8a8578]">
        {icon}
        <span>{label}</span>
      </div>
      {badge ? (
        <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${badgeClass}`}>
          {value}
        </span>
      ) : (
        <span className="font-medium truncate max-w-[180px]">{value}</span>
      )}
    </div>
  );
}

function SummaryCard({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Clock;
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-lg border border-[#e0dbd0] bg-white p-3 text-center">
      <div className="flex items-center justify-center gap-1.5 mb-1">
        <Icon className="h-3 w-3 text-[#8a8578]/60" />
        <span className="text-[10px] uppercase tracking-wider text-[#8a8578]/60">
          {label}
        </span>
      </div>
      <div className="text-sm font-medium">{value}</div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Gateway Actions
// ---------------------------------------------------------------------------

function GatewayActions({ onRefresh }: { onRefresh: () => void }) {
  const callRpc = useGatewayRpcMutation();
  const [busy, setBusy] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<{
    type: "success" | "error";
    message: string;
  } | null>(null);

  const runAction = useCallback(
    async (
      label: string,
      method: string,
      params?: Record<string, unknown>,
      postAction?: () => void,
    ) => {
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

  return (
    <div className="space-y-3">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-[#8a8578]">
        Quick Actions
      </h3>

      {feedback && (
        <div
          className={cn(
            "flex items-center gap-2 rounded-md border p-2.5 text-xs",
            feedback.type === "success"
              ? "border-[#2d8a4e]/30 bg-[#e8f5e9] text-[#2d8a4e]"
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
            className="text-[#8a8578] hover:text-[#1a1a1a]"
            onClick={() => setFeedback(null)}
          >
            dismiss
          </button>
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        <ActionButton
          icon={RotateCcw}
          label="Reload Config"
          busy={busy}
          busyKey="Reload Config"
          onClick={() => runAction("Reload Config", "config.apply", {}, onRefresh)}
        />
        <ActionButton
          icon={Download}
          label="Update Gateway"
          busy={busy}
          busyKey="Update Gateway"
          onClick={() => {
            if (!window.confirm("Update gateway? This will restart the service.")) return;
            runAction("Update Gateway", "update.run", {}, () =>
              setTimeout(onRefresh, 5000),
            );
          }}
        />
        <ActionButton
          icon={Radio}
          label="Probe Channels"
          busy={busy}
          busyKey="Probe Channels"
          onClick={() =>
            runAction("Probe Channels", "channels.status", {
              probe: true,
              timeoutMs: 8000,
            })
          }
        />
        <ActionButton
          icon={Activity}
          label="Health Check"
          busy={busy}
          busyKey="Health Check"
          onClick={() => runAction("Health Check", "health", {}, onRefresh)}
        />
      </div>
    </div>
  );
}

function ActionButton({
  icon: Icon,
  label,
  busy,
  busyKey,
  onClick,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  busy: string | null;
  busyKey: string;
  onClick: () => void;
}) {
  const isBusy = busy === busyKey;
  return (
    <button
      className="flex items-center gap-2 rounded-lg border border-[#e0dbd0] bg-white p-2.5 text-left transition-colors hover:bg-[#f3efe6] disabled:opacity-50 disabled:cursor-not-allowed"
      disabled={busy !== null}
      onClick={onClick}
    >
      {isBusy ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin text-[#8a8578] shrink-0" />
      ) : (
        <Icon className="h-3.5 w-3.5 text-[#8a8578] shrink-0" />
      )}
      <span className="text-xs font-medium">{label}</span>
    </button>
  );
}
