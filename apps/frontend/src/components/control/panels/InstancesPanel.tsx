"use client";

import { Loader2, RefreshCw, Monitor } from "lucide-react";
import { useGatewayRpc } from "@/hooks/useGatewayRpc";
import { Button } from "@/components/ui/button";

interface PresenceEntry {
  instanceId: string;
  host?: string;
  ip?: string;
  version?: string;
  platform?: string;
  lastInputSeconds?: number;
  [key: string]: unknown;
}

interface LegacyInstance {
  id: string;
  status?: string;
  agent?: string;
  uptime?: number;
  [key: string]: unknown;
}

export function InstancesPanel() {
  const {
    data: presenceData,
    error: presenceError,
    isLoading: presenceLoading,
    mutate: mutatePresence,
  } = useGatewayRpc<PresenceEntry[] | Record<string, unknown>>("system-presence");

  // Fallback to node.list if system-presence fails
  const useFallback = !!presenceError;
  const {
    data: fallbackData,
    error: fallbackError,
    isLoading: fallbackLoading,
    mutate: mutateFallback,
  } = useGatewayRpc<LegacyInstance[]>(useFallback ? "node.list" : null);

  const isLoading = presenceLoading || (useFallback && fallbackLoading);
  const error = useFallback ? fallbackError : presenceError;
  const mutate = useFallback ? mutateFallback : mutatePresence;

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

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

  // Render presence entries
  if (!useFallback) {
    const entries: PresenceEntry[] = Array.isArray(presenceData) ? presenceData : [];

    return (
      <div className="p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">Instances</h2>
          <Button variant="ghost" size="sm" onClick={() => mutate()}>
            <RefreshCw className="h-3.5 w-3.5" />
          </Button>
        </div>

        {entries.length === 0 ? (
          <p className="text-sm text-muted-foreground">No active instances.</p>
        ) : (
          <div className="space-y-2">
            {entries.map((entry) => (
              <div key={entry.instanceId} className="flex items-center gap-3 rounded-lg border border-border p-3">
                <Monitor className="h-4 w-4 opacity-50" />
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium">{entry.host || entry.instanceId}</div>
                  <div className="text-xs text-muted-foreground">
                    {[
                      entry.platform,
                      entry.version && `v${entry.version}`,
                      entry.ip,
                      entry.lastInputSeconds != null && `idle ${entry.lastInputSeconds}s`,
                    ]
                      .filter(Boolean)
                      .join(" \u00b7 ") || "unknown"}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  }

  // Fallback: render legacy node.list format
  const instances = Array.isArray(fallbackData) ? fallbackData : [];

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Instances</h2>
        <Button variant="ghost" size="sm" onClick={() => mutate()}>
          <RefreshCw className="h-3.5 w-3.5" />
        </Button>
      </div>

      {instances.length === 0 ? (
        <p className="text-sm text-muted-foreground">No active instances.</p>
      ) : (
        <div className="space-y-2">
          {instances.map((inst) => (
            <div key={inst.id} className="flex items-center gap-3 rounded-lg border border-border p-3">
              <Monitor className="h-4 w-4 opacity-50" />
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium">{inst.agent || inst.id}</div>
                <div className="text-xs text-muted-foreground">{inst.status || "unknown"}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
