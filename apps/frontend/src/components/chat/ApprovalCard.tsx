import * as React from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { ApprovalRequest, ExecApprovalDecision } from "./MessageList";

export interface ApprovalCardProps {
  pending: ApprovalRequest;
  onDecide: (decision: ExecApprovalDecision) => Promise<void>;
}

const HOST_LABEL: Record<ApprovalRequest["host"], string> = {
  gateway: "container",
  node: "node",
  sandbox: "sandbox",
};

export function ApprovalCard({ pending, onDecide }: ApprovalCardProps) {
  const [detailsOpen, setDetailsOpen] = React.useState(false);
  const allowsOnce = pending.allowedDecisions.includes("allow-once");
  const allowsAlways = pending.allowedDecisions.includes("allow-always");
  const allowsDeny = pending.allowedDecisions.includes("deny");
  const handle = (d: ExecApprovalDecision) => () => { void onDecide(d); };
  const trustScopeLine = pending.resolvedPath
    ? `Trust will always allow ${pending.resolvedPath} on this ${pending.host === "node" ? "Mac" : "agent"} (any arguments).`
    : "Trust will always allow this command (any arguments).";

  return (
    <div className="my-2 max-w-xl rounded-md border border-[#e0dbd0] bg-[#faf7f2] p-3 text-sm">
      <div className="flex items-start justify-between gap-2">
        <div className="font-mono text-[#1a1a1a] break-all">{pending.command}</div>
        <span className="inline-flex items-center px-2 py-0.5 text-xs rounded bg-[#e8e3d9] text-[#302d28]">
          {HOST_LABEL[pending.host]}
        </span>
      </div>
      {pending.cwd && <div className="mt-1 text-xs text-[#8a8578]">{pending.cwd}</div>}
      {pending.agentId && <div className="text-xs text-[#8a8578]">{pending.agentId}</div>}

      <div className="mt-3 flex gap-2">
        <Button size="sm" variant="default" disabled={!allowsOnce} onClick={handle("allow-once")}>
          Allow once
        </Button>
        <Button size="sm" variant="secondary" disabled={!allowsAlways} onClick={handle("allow-always")}>
          Trust
        </Button>
        <Button size="sm" variant="ghost" disabled={!allowsDeny} onClick={handle("deny")}>
          Deny
        </Button>
      </div>

      <button
        type="button"
        onClick={() => setDetailsOpen((v) => !v)}
        className="mt-3 inline-flex items-center gap-1 text-xs text-[#8a8578] hover:text-[#302d28]"
      >
        {detailsOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        Details
      </button>
      {detailsOpen && (
        <div className="mt-2 space-y-1 text-xs text-[#302d28]">
          {pending.resolvedPath && (
            <div>
              <span className="text-[#8a8578]">Resolves to </span>
              <span className="font-mono">{pending.resolvedPath}</span>
            </div>
          )}
          {pending.commandArgv && (
            <div>
              <span className="text-[#8a8578]">argv </span>
              <span className="font-mono">{JSON.stringify(pending.commandArgv)}</span>
            </div>
          )}
          {pending.sessionKey && (
            <div>
              <span className="text-[#8a8578]">Session </span>
              <span className="font-mono">{pending.sessionKey}</span>
            </div>
          )}
          {allowsAlways && <div className="text-[#8a8578] pt-1">{trustScopeLine}</div>}
        </div>
      )}
    </div>
  );
}
