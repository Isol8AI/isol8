import { formatTokens, formatRelativeTime } from "./formatters";
import type { CronRunEntry } from "./types";

const DELIVERY_STATUS_LABEL: Record<string, string> = {
  delivered: "✓ Delivered",
  "not-delivered": "✗ Delivery failed",
  unknown: "Delivery unknown",
  "not-requested": "No delivery configured",
};

export function RunMetadata({
  run,
  nextRunAtMs,
}: {
  run: CronRunEntry;
  nextRunAtMs: number | undefined;
}) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 px-6 py-4 text-sm border-t border-[#e0dbd0]">
      {run.model && (
        <>
          <dt className="text-[#8a8578]">Model</dt>
          <dd>
            {run.model}
            {run.provider ? ` · ${run.provider}` : ""}
          </dd>
        </>
      )}
      {run.usage && (
        <>
          <dt className="text-[#8a8578]">Tokens</dt>
          <dd>{formatTokens(run.usage)}</dd>
        </>
      )}
      {run.deliveryStatus && (
        <>
          <dt className="text-[#8a8578]">Delivery</dt>
          <dd>
            {DELIVERY_STATUS_LABEL[run.deliveryStatus] ?? run.deliveryStatus}
            {run.deliveryError && (
              <div className="text-xs text-destructive">{run.deliveryError}</div>
            )}
          </dd>
        </>
      )}
      {run.sessionId && (
        <>
          <dt className="text-[#8a8578]">Session</dt>
          <dd className="font-mono text-xs">{run.sessionId.slice(0, 8)}…</dd>
        </>
      )}
      {nextRunAtMs && (
        <>
          <dt className="text-[#8a8578]">Next run</dt>
          <dd>{formatRelativeTime(nextRunAtMs)}</dd>
        </>
      )}
    </dl>
  );
}
