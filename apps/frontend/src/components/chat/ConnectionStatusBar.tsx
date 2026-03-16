"use client";

import { useCallback, useEffect, useState } from "react";
import { Wifi, WifiOff, RefreshCw, RotateCcw, Loader2 } from "lucide-react";
import { useGateway } from "@/hooks/useGateway";
import { useGatewayRpc } from "@/hooks/useGatewayRpc";
import { useContainerStatus } from "@/hooks/useContainerStatus";
import { useApi } from "@/lib/api";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ConnectionState =
  | "connected"
  | "connecting"
  | "disconnected"
  | "container_starting"
  | "container_down";

interface HealthData {
  ok?: boolean;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Style mappings
// ---------------------------------------------------------------------------

const stateStyles: Record<ConnectionState, string> = {
  connected:
    "bg-emerald-500/10 border-emerald-500/20 text-emerald-700 dark:text-emerald-400",
  connecting:
    "bg-yellow-500/10 border-yellow-500/20 text-yellow-700 dark:text-yellow-400",
  disconnected:
    "bg-red-500/10 border-red-500/20 text-red-700 dark:text-red-400",
  container_starting:
    "bg-yellow-500/10 border-yellow-500/20 text-yellow-700 dark:text-yellow-400",
  container_down:
    "bg-red-500/10 border-red-500/20 text-red-700 dark:text-red-400",
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ConnectionStatusBar() {
  const { isConnected, reconnectAttempt, reconnect } = useGateway();
  const { post } = useApi();

  // Poll gateway health via WS RPC (every 5s while connected)
  const { data: health } = useGatewayRpc<HealthData>(
    isConnected ? "health" : null,
    undefined,
    { refreshInterval: 5000, dedupingInterval: 4000 },
  );

  // Poll container status via REST when WS is disconnected
  const shouldPollContainer = !isConnected;
  const { container } = useContainerStatus({
    refreshInterval: shouldPollContainer ? 5000 : 0,
    enabled: shouldPollContainer,
  });

  const [hiddenForState, setHiddenForState] = useState<ConnectionState | null>(null);
  const [restarting, setRestarting] = useState(false);

  // ---------------------------------------------------------------------------
  // Derive connection state
  // ---------------------------------------------------------------------------

  const connectionState: ConnectionState = (() => {
    if (isConnected && health?.ok !== false) return "connected";
    if (isConnected && health?.ok === false) return "connecting";
    if (!isConnected && reconnectAttempt > 0 && reconnectAttempt <= 10)
      return "connecting";
    if (!isConnected && container?.status === "provisioning")
      return "container_starting";
    if (!isConnected && container?.status === "running") return "disconnected";
    if (
      !isConnected &&
      (container === null ||
        container === undefined ||
        container?.status === "stopped" ||
        container?.status === "error")
    )
      return "container_down";
    return "disconnected";
  })();

  // ---------------------------------------------------------------------------
  // Auto-hide when connected (timer sets hiddenForState to current state)
  // Bar is hidden only when hiddenForState matches current connectionState
  // ---------------------------------------------------------------------------

  useEffect(() => {
    if (connectionState !== "connected") return;
    const timer = setTimeout(() => setHiddenForState("connected"), 3000);
    return () => clearTimeout(timer);
  }, [connectionState]);

  // ---------------------------------------------------------------------------
  // Auto-reconnect when container comes back and attempts exhausted
  // ---------------------------------------------------------------------------

  useEffect(() => {
    if (
      !isConnected &&
      container?.status === "running" &&
      reconnectAttempt >= 10
    ) {
      reconnect();
    }
  }, [isConnected, container?.status, reconnectAttempt, reconnect]);

  // ---------------------------------------------------------------------------
  // Restart gateway handler
  // ---------------------------------------------------------------------------

  const handleRestartGateway = useCallback(async () => {
    setRestarting(true);
    try {
      await post("/container/gateway/restart", {});
      // Wait 2 seconds for the gateway to come back up, then reconnect
      setTimeout(() => {
        reconnect();
        setRestarting(false);
      }, 2000);
    } catch {
      setRestarting(false);
    }
  }, [post, reconnect]);

  // ---------------------------------------------------------------------------
  // Render helpers
  // ---------------------------------------------------------------------------

  // Hidden only when the timer fired for the CURRENT state (auto-resets on state change)
  if (hiddenForState === connectionState) return null;

  const icon = (() => {
    switch (connectionState) {
      case "connected":
        return <Wifi className="h-4 w-4 shrink-0" />;
      case "connecting":
      case "container_starting":
        return <Loader2 className="h-4 w-4 shrink-0 animate-spin" />;
      case "disconnected":
      case "container_down":
        return <WifiOff className="h-4 w-4 shrink-0" />;
    }
  })();

  const message = (() => {
    switch (connectionState) {
      case "connected":
        return "Connected";
      case "connecting":
        return reconnectAttempt > 0
          ? `Connecting... (attempt ${reconnectAttempt}/10)`
          : "Connecting...";
      case "disconnected":
        return "Disconnected";
      case "container_starting":
        return "Your agent is starting up...";
      case "container_down":
        return "Your agent is offline";
    }
  })();

  return (
    <div
      className={cn(
        "flex items-center justify-between gap-3 px-3 py-1.5 text-sm border rounded-md",
        stateStyles[connectionState],
      )}
    >
      <div className="flex items-center gap-2 min-w-0">
        {icon}
        <span className="truncate">{message}</span>
      </div>

      <div className="flex items-center gap-2 shrink-0">
        {connectionState === "disconnected" && (
          <button
            onClick={reconnect}
            className="inline-flex items-center gap-1.5 px-2 py-0.5 text-xs font-medium rounded hover:bg-black/5 dark:hover:bg-white/5 transition-colors"
          >
            <RefreshCw className="h-3 w-3" />
            Reconnect
          </button>
        )}

        {connectionState === "container_down" && (
          <button
            onClick={handleRestartGateway}
            disabled={restarting}
            className="inline-flex items-center gap-1.5 px-2 py-0.5 text-xs font-medium rounded hover:bg-black/5 dark:hover:bg-white/5 transition-colors disabled:opacity-50"
          >
            {restarting ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <RotateCcw className="h-3 w-3" />
            )}
            Restart Gateway
          </button>
        )}
      </div>
    </div>
  );
}
