import * as React from "react";
import type { ApprovalRequest, ExecApprovalDecision } from "./MessageList";

export interface ApprovalCardProps {
  pending: ApprovalRequest;
  onDecide: (decision: ExecApprovalDecision) => Promise<void>;
}

export function ApprovalCard({ pending }: ApprovalCardProps) {
  return (
    <div className="my-2 max-w-xl rounded-md border border-[#e0dbd0] bg-[#faf7f2] p-3 text-sm">
      <div className="font-mono text-[#1a1a1a]">{pending.command}</div>
    </div>
  );
}
