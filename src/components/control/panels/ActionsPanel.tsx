"use client";

import { useState, useCallback } from "react";
import {
  Loader2,
  RefreshCw,
  ShieldCheck,
  UserCheck,
  UserX,
  Radio,
  AlertCircle,
  CheckCircle2,
  KeyRound,
} from "lucide-react";
import { useGatewayRpc, useGatewayRpcMutation } from "@/hooks/useGatewayRpc";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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

  // Manual code input
  const [codeInput, setCodeInput] = useState("");

  // Action feedback
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

  const handleApproveCode = () => {
    const code = codeInput.trim().toUpperCase();
    if (!code) return;
    runAction("Approve pairing", "device.pair.approve", { code }, () => {
      setCodeInput("");
      mutatePairing();
    });
  };

  const requests = pairingData?.requests ?? [];

  return (
    <div className="p-6 space-y-6 overflow-auto">
      {/* Header */}
      <div>
        <h2 className="text-lg font-semibold">Device Pairing</h2>
        <p className="text-xs text-muted-foreground">
          Approve or reject pairing requests from messaging channels.
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
            onClick={() => setFeedback(null)}
          >
            dismiss
          </button>
        </div>
      )}

      {/* ── Manual Code Approval ─────────────────────── */}
      <section className="space-y-3">
        <div className="flex items-center gap-2">
          <KeyRound className="h-4 w-4 text-muted-foreground" />
          <h3 className="text-sm font-semibold">Approve by Code</h3>
        </div>
        <p className="text-xs text-muted-foreground">
          When someone messages your bot for the first time, they receive a pairing code.
          Enter it here to approve access.
        </p>
        <div className="flex items-center gap-2">
          <Input
            className="h-9 w-48 font-mono uppercase text-sm tracking-wider"
            placeholder="ABCD1234"
            value={codeInput}
            onChange={(e) => setCodeInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleApproveCode();
            }}
            maxLength={12}
          />
          <Button
            size="sm"
            className="bg-emerald-600 hover:bg-emerald-700"
            disabled={!codeInput.trim() || busy !== null}
            onClick={handleApproveCode}
          >
            {busy === "Approve pairing" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />
            ) : (
              <UserCheck className="h-3.5 w-3.5 mr-1" />
            )}
            Approve
          </Button>
        </div>
      </section>

      {/* ── Pending Requests ─────────────────────────── */}
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-muted-foreground" />
            <h3 className="text-sm font-semibold">Pending Requests</h3>
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
            No pending pairing requests. When someone messages your bot for the
            first time, their request will appear here.
          </p>
        ) : (
          <div className="space-y-2">
            {requests.map((req) => (
              <div
                key={req.code}
                className="rounded-lg border border-border p-3 space-y-2"
              >
                <div className="min-w-0">
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
                    <span>
                      Code:{" "}
                      <code className="font-mono bg-muted/30 px-1 rounded">
                        {req.code}
                      </code>
                    </span>
                    <span>{formatRelativeTime(req.createdAt)}</span>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <Button
                    size="sm"
                    className="h-7 text-xs bg-emerald-600 hover:bg-emerald-700"
                    disabled={busy !== null}
                    onClick={() =>
                      runAction(
                        `Approve ${req.code}`,
                        "device.pair.approve",
                        { code: req.code },
                        () => mutatePairing(),
                      )
                    }
                  >
                    {busy === `Approve ${req.code}` ? (
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
                      runAction(
                        `Reject ${req.code}`,
                        "device.pair.reject",
                        { code: req.code },
                        () => mutatePairing(),
                      )
                    }
                  >
                    {busy === `Reject ${req.code}` ? (
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
    </div>
  );
}
