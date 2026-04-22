import Link from "next/link";
import { auth } from "@clerk/nextjs/server";

import { getActions, type AdminAction } from "@/app/admin/_lib/api";
import { AuditRow, type AuditEntry } from "@/components/admin/AuditRow";
import { EmptyState } from "@/components/admin/EmptyState";
import { ErrorBanner } from "@/components/admin/ErrorBanner";

export const metadata = { title: "Actions \u00b7 Admin" };

// ---------------------------------------------------------------------------
// AdminAction (intentionally permissive in `_lib/api.ts`) → AuditEntry
// (the strict shape `<AuditRow>` expects). Defaults to safe values when the
// backend hasn't filled a field.
// ---------------------------------------------------------------------------

function asAuditEntry(raw: AdminAction): AuditEntry {
  // Backend uses `timestamp_action_id` as the composite sort key, but the
  // permissive type uses both `timestamp` and `action_id`. Compose the
  // composite if it isn't already present.
  const compositeKey =
    typeof (raw as Record<string, unknown>).timestamp_action_id === "string"
      ? ((raw as Record<string, unknown>).timestamp_action_id as string)
      : raw.timestamp && raw.action_id
        ? `${raw.timestamp}#${raw.action_id}`
        : (raw.timestamp ?? "");

  const result =
    raw.status === "error" || raw.status === "success"
      ? raw.status
      : ((raw as Record<string, unknown>).result === "error" ||
            (raw as Record<string, unknown>).result === "success"
          ? ((raw as Record<string, unknown>).result as "success" | "error")
          : "success");

  const auditStatus =
    (raw as Record<string, unknown>).audit_status === "panic" ||
    (raw as Record<string, unknown>).audit_status === "written"
      ? ((raw as Record<string, unknown>).audit_status as
          | "written"
          | "panic")
      : "written";

  const httpStatus =
    typeof (raw as Record<string, unknown>).http_status === "number"
      ? ((raw as Record<string, unknown>).http_status as number)
      : 0;

  const elapsedMs =
    typeof (raw as Record<string, unknown>).elapsed_ms === "number"
      ? ((raw as Record<string, unknown>).elapsed_ms as number)
      : 0;

  const errorMessage =
    typeof (raw as Record<string, unknown>).error_message === "string"
      ? ((raw as Record<string, unknown>).error_message as string)
      : undefined;

  return {
    admin_user_id: raw.admin_user_id ?? "",
    timestamp_action_id: compositeKey,
    target_user_id: raw.target_user_id ?? "",
    action: raw.action ?? "",
    result,
    audit_status: auditStatus,
    http_status: httpStatus,
    elapsed_ms: elapsedMs,
    error_message: errorMessage,
  };
}

interface ActionsPageProps {
  params: Promise<{ id: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

function parseCursor(input: string | string[] | undefined): string | undefined {
  const v = Array.isArray(input) ? input[0] : input;
  return v && v.length > 0 ? v : undefined;
}

export default async function ActionsPage({
  params,
  searchParams,
}: ActionsPageProps) {
  const { id } = await params;
  const sp = await searchParams;
  const cursor = parseCursor(sp.cursor);

  const { getToken } = await auth();
  const token = await getToken();
  if (!token) {
    return (
      <div className="space-y-6">
        <h1 className="text-xl font-semibold text-zinc-100">Actions</h1>
        <ErrorBanner error="Missing Clerk session token." />
      </div>
    );
  }

  const result = await getActions(token, {
    target_user_id: id,
    limit: 100,
    cursor,
  });

  const entries = (result.items ?? []).map(asAuditEntry);

  const nextCursorHref = result.cursor
    ? `/admin/users/${encodeURIComponent(id)}/actions?cursor=${encodeURIComponent(result.cursor)}`
    : null;

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold text-zinc-100">Admin actions</h1>

      {entries.length === 0 ? (
        <EmptyState
          title="No admin actions"
          body="No admin has taken any action against this user yet."
        />
      ) : (
        <div className="space-y-1.5">
          {entries.map((entry) => (
            <AuditRow
              key={`${entry.timestamp_action_id}-${entry.action}`}
              entry={entry}
            />
          ))}
        </div>
      )}

      {nextCursorHref ? (
        <div className="flex justify-center">
          <Link
            href={nextCursorHref}
            className="rounded-md border border-white/10 bg-white/[0.04] px-4 py-2 text-sm text-zinc-100 hover:bg-white/[0.08]"
          >
            Load more
          </Link>
        </div>
      ) : null}
    </div>
  );
}
