"use client";

import { Loader2, CheckCircle2, Check, X } from "lucide-react";
import { useState } from "react";
import { usePaperclipApi, usePaperclipMutation } from "@/hooks/usePaperclip";
import { Button } from "@/components/ui/button";

interface Approval {
  id?: string;
  description?: string;
  requester?: string;
  timestamp?: string;
}

function formatTime(ts?: string) {
  if (!ts) return "—";
  const date = new Date(ts);
  const ago = Date.now() - date.getTime();
  const minutes = Math.floor(ago / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function ApprovalCard({ approval, onDone }: { approval: Approval; onDone: () => void }) {
  const mutation = usePaperclipMutation();
  const [isActing, setIsActing] = useState<"approve" | "reject" | null>(null);

  const act = async (action: "approve" | "reject") => {
    setIsActing(action);
    try {
      await mutation.post(`approvals/${approval.id}/${action}`);
      onDone();
    } finally {
      setIsActing(null);
    }
  };

  return (
    <div className="rounded-lg border border-[#e5e0d5] bg-white p-4 space-y-3">
      <div>
        <p className="text-sm text-[#1a1a1a]">{approval.description ?? "No description"}</p>
        <div className="flex items-center gap-2 mt-1">
          {approval.requester && (
            <span className="text-xs text-[#8a8578]">from {approval.requester}</span>
          )}
          <span className="text-xs text-[#b0a99a]">{formatTime(approval.timestamp)}</span>
        </div>
      </div>
      <div className="flex gap-2">
        <Button
          size="sm"
          onClick={() => act("approve")}
          disabled={isActing !== null}
          className="bg-[#2d8a4e] hover:bg-[#246840] text-white"
        >
          {isActing === "approve" ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />
          ) : (
            <Check className="h-3.5 w-3.5 mr-1" />
          )}
          Approve
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={() => act("reject")}
          disabled={isActing !== null}
          className="text-red-600 border-red-200 hover:bg-red-50"
        >
          {isActing === "reject" ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />
          ) : (
            <X className="h-3.5 w-3.5 mr-1" />
          )}
          Reject
        </Button>
      </div>
    </div>
  );
}

export function ApprovalsPanel() {
  const { data, isLoading, refresh } = usePaperclipApi<Approval[]>("approvals");

  const approvals = Array.isArray(data) ? data : [];

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-[#8a8578]" />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-[#1a1a1a]">Approvals</h1>
        <p className="text-sm text-[#8a8578]">{approvals.length} pending</p>
      </div>

      {approvals.length === 0 ? (
        <div className="rounded-lg border border-[#e5e0d5] bg-white p-8 text-center">
          <CheckCircle2 className="h-6 w-6 text-[#b0a99a] mx-auto mb-2" />
          <p className="text-sm text-[#8a8578]">No pending approvals</p>
        </div>
      ) : (
        <div className="space-y-3">
          {approvals.map((approval, idx) => (
            <ApprovalCard
              key={approval.id ?? idx}
              approval={approval}
              onDone={() => refresh()}
            />
          ))}
        </div>
      )}
    </div>
  );
}
