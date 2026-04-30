import { listPendingTakedowns } from "@/app/admin/_actions/marketplace";

import { TakedownActions } from "./TakedownActions";

export const metadata = { title: "Takedowns · Admin" };
// Always re-fetch on navigation: moderators expect fresh queue contents and
// `router.refresh()` after a grant must produce up-to-date data.
export const dynamic = "force-dynamic";

interface PendingTakedown {
  listing_id: string;
  takedown_id: string;
  reason: string;
  filed_by_name: string;
  filed_by_email: string;
  basis_md: string;
}

/**
 * Pending takedowns queue (Server Component).
 *
 * Fetches `/admin/marketplace/takedowns?status=pending` via the
 * `listPendingTakedowns` Server Action which returns an `ActionResult`
 * envelope `{ ok, status, data?, error? }`. Errors render inline; the typed
 * grant action lives in `TakedownActions` (a Client Component) so the page
 * itself stays a pure RSC.
 */
export default async function TakedownsQueue() {
  const result = await listPendingTakedowns();
  if (!result.ok) {
    return (
      <p className="text-sm text-red-400" role="alert">
        Error loading takedowns: {result.error ?? `http_${result.status}`}
      </p>
    );
  }

  const items =
    (result.data as { items?: PendingTakedown[] } | undefined)?.items ?? [];

  if (items.length === 0) {
    return <p className="text-sm text-zinc-400">No pending takedowns.</p>;
  }

  return (
    <div className="space-y-3">
      <h1 className="text-2xl font-semibold text-neutral-100">Takedowns</h1>
      <p className="text-sm text-zinc-500">
        {items.length} request{items.length === 1 ? "" : "s"} awaiting review.
      </p>
      <ul className="space-y-3">
        {items.map((td) => (
          <li
            key={td.takedown_id}
            className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-5"
          >
            <div className="mb-3 flex items-start justify-between gap-4">
              <div className="min-w-0 flex-1">
                <p className="font-semibold text-zinc-100">
                  listing:{" "}
                  <span className="font-mono text-zinc-300">
                    {td.listing_id}
                  </span>
                </p>
                <p className="mt-1 text-sm text-zinc-400">
                  reason: {td.reason}
                </p>
                <p className="mt-1 text-sm text-zinc-400">
                  filed by: {td.filed_by_name} ({td.filed_by_email})
                </p>
              </div>
              <TakedownActions
                listingId={td.listing_id}
                takedownId={td.takedown_id}
              />
            </div>
            <p className="whitespace-pre-line rounded bg-zinc-950 p-3 text-sm text-zinc-200">
              {td.basis_md}
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}
