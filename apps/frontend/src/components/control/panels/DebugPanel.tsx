"use client";

import { Loader2, RefreshCw, ChevronDown } from "lucide-react";
import { useGatewayRpc } from "@/hooks/useGatewayRpc";
import { Button } from "@/components/ui/button";

interface DebugSection {
  label: string;
  method: string;
}

const SECTIONS: DebugSection[] = [
  { label: "Status", method: "status" },
  { label: "Health", method: "health" },
  { label: "Models", method: "models.list" },
  { label: "Last Heartbeat", method: "last-heartbeat" },
];

function DebugSectionView({ label, method }: DebugSection) {
  const { data, error, isLoading } = useGatewayRpc<unknown>(method);

  return (
    <details className="group rounded-lg border border-border overflow-hidden" open>
      <summary className="flex items-center justify-between px-4 py-2.5 cursor-pointer hover:bg-muted/30 select-none">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">{label}</span>
          <span className="text-[10px] text-muted-foreground/50 font-mono">{method}</span>
        </div>
        <div className="flex items-center gap-2">
          {isLoading && <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />}
          {error && <span className="text-[10px] text-destructive">error</span>}
          <ChevronDown className="h-3.5 w-3.5 text-muted-foreground transition-transform group-open:rotate-180" />
        </div>
      </summary>
      <div className="border-t border-border">
        {error ? (
          <div className="px-4 py-3 text-xs text-destructive">{error.message}</div>
        ) : (
          <pre className="text-xs bg-muted/20 p-3 overflow-auto max-h-64">
            {data ? JSON.stringify(data, null, 2) : "No data."}
          </pre>
        )}
      </div>
    </details>
  );
}

export function DebugPanel() {
  // We use individual hooks per section (they call in parallel via SWR).
  // The refresh button triggers revalidation on all by re-rendering.
  const { mutate: mutateStatus } = useGatewayRpc<unknown>("status");
  const { mutate: mutateHealth } = useGatewayRpc<unknown>("health");
  const { mutate: mutateModels } = useGatewayRpc<unknown>("models.list");
  const { mutate: mutateHeartbeat } = useGatewayRpc<unknown>("last-heartbeat");

  const refreshAll = () => {
    mutateStatus();
    mutateHealth();
    mutateModels();
    mutateHeartbeat();
  };

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Debug</h2>
        <Button variant="ghost" size="sm" onClick={refreshAll}>
          <RefreshCw className="h-3.5 w-3.5" />
        </Button>
      </div>

      <div className="space-y-3">
        {SECTIONS.map((section) => (
          <DebugSectionView key={section.method} {...section} />
        ))}
      </div>
    </div>
  );
}
