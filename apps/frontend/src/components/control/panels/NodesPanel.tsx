"use client";

import { Loader2, RefreshCw, Network } from "lucide-react";
import { useGatewayRpc } from "@/hooks/useGatewayRpc";
import { Button } from "@/components/ui/button";

interface Node {
  id: string;
  name?: string;
  status?: string;
  type?: string;
  [key: string]: unknown;
}

export function NodesPanel() {
  const { data, error, isLoading, mutate } = useGatewayRpc<Node[]>("node.list");

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

  const nodes = Array.isArray(data) ? data : [];

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Nodes</h2>
        <Button variant="ghost" size="sm" onClick={() => mutate()}>
          <RefreshCw className="h-3.5 w-3.5" />
        </Button>
      </div>

      {nodes.length === 0 ? (
        <p className="text-sm text-muted-foreground">No nodes connected.</p>
      ) : (
        <div className="space-y-2">
          {nodes.map((node) => (
            <div key={node.id} className="flex items-center gap-3 rounded-lg border border-border p-3">
              <Network className="h-4 w-4 opacity-50" />
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium">{node.name || node.id}</div>
                <div className="text-xs text-muted-foreground">{node.type || "—"} · {node.status || "unknown"}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
