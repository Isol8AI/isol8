import * as React from "react";

import { cn } from "@/lib/utils";

export interface AuditEntry {
  admin_user_id: string;
  /** Composite sort key: `{ISO8601}#{ulid}`. */
  timestamp_action_id: string;
  target_user_id: string;
  /** Dotted action name, e.g. `container.reprovision`. */
  action: string;
  result: "success" | "error";
  audit_status?: "written" | "panic";
  http_status: number;
  elapsed_ms: number;
  error_message?: string;
}

export interface AuditRowProps {
  entry: AuditEntry;
  /** Optional row click handler; renders the row as a button when present. */
  onClick?: () => void;
}

function splitTimestamp(compositeKey: string): string {
  const hashIdx = compositeKey.indexOf("#");
  return hashIdx === -1 ? compositeKey : compositeKey.slice(0, hashIdx);
}

/**
 * One row of the admin audit log table. Server-Component-friendly.
 */
export function AuditRow({ entry, onClick }: AuditRowProps) {
  const timestamp = splitTimestamp(entry.timestamp_action_id);
  const isPanic = entry.audit_status === "panic";
  const isError = entry.result === "error";

  const Wrapper: React.ElementType = onClick ? "button" : "div";

  return (
    <Wrapper
      type={onClick ? "button" : undefined}
      onClick={onClick}
      title={`HTTP ${entry.http_status} \u00b7 ${entry.elapsed_ms}ms${entry.error_message ? ` \u00b7 ${entry.error_message}` : ""}`}
      className={cn(
        "grid w-full grid-cols-[180px_minmax(180px,1fr)_minmax(160px,1fr)_auto_auto] items-center gap-3 rounded-md border border-white/5 bg-white/[0.02] px-3 py-2 text-left text-xs",
        onClick && "cursor-pointer transition-colors hover:bg-white/[0.04]",
      )}
      data-result={entry.result}
      data-audit-status={entry.audit_status ?? "written"}
    >
      <time className="font-mono text-zinc-400" dateTime={timestamp}>
        {timestamp}
      </time>
      <span className="truncate font-mono text-zinc-100">{entry.action}</span>
      <span className="truncate text-zinc-300">{entry.target_user_id}</span>
      <span
        className={cn(
          "rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
          isError
            ? "bg-red-500/15 text-red-300"
            : "bg-emerald-500/15 text-emerald-300",
        )}
      >
        {entry.result}
      </span>
      {isPanic ? (
        <span
          className="rounded bg-yellow-500/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-yellow-300"
          title="Audit row failed to write to DynamoDB; see CloudWatch"
        >
          {"audit panic \u2014 see CloudWatch"}
        </span>
      ) : (
        <span aria-hidden="true" />
      )}
    </Wrapper>
  );
}
