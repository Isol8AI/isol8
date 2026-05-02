import Link from "next/link";

import { listReviewQueue } from "@/app/admin/_actions/marketplace";

import { ModerationActions } from "./ModerationActions";

export const metadata = { title: "Review queue · Admin" };
// Always re-fetch on navigation: moderators expect fresh queue contents and
// `router.refresh()` after approve/reject must produce up-to-date data.
export const dynamic = "force-dynamic";

interface ReviewQueueListing {
  listing_id: string;
  name: string;
  slug: string;
  format: string;
  price_cents: number;
  description_md: string;
  seller_id: string;
}

/**
 * Listings review queue (Server Component).
 *
 * Fetches `/admin/marketplace/listings` via the `listReviewQueue` Server
 * Action which returns an `ActionResult` envelope `{ ok, status, data?, error? }`.
 * Errors render inline; the typed actions live in `ModerationActions` (a
 * Client Component) so the page itself stays a pure RSC.
 */
export default async function ListingsReview() {
  const result = await listReviewQueue();
  if (!result.ok) {
    return (
      <p className="text-sm text-red-400" role="alert">
        Error loading review queue: {result.error ?? `http_${result.status}`}
      </p>
    );
  }

  const items =
    (result.data as { items?: ReviewQueueListing[] } | undefined)?.items ?? [];

  if (items.length === 0) {
    return (
      <p className="text-sm text-zinc-400">No listings awaiting review.</p>
    );
  }

  return (
    <div className="space-y-3">
      <h1 className="text-2xl font-semibold text-neutral-100">Review queue</h1>
      <p className="text-sm text-zinc-500">
        {items.length} listing{items.length === 1 ? "" : "s"} awaiting moderation.
      </p>
      <ul className="space-y-3">
        {items.map((listing) => (
          <li
            key={listing.listing_id}
            className="flex items-start justify-between gap-4 rounded-lg border border-zinc-800 bg-zinc-900/40 p-5"
          >
            <div className="min-w-0 flex-1">
              <h3 className="font-semibold text-zinc-100">
                <Link
                  href={`/admin/marketplace/listings/${listing.listing_id}`}
                  className="hover:underline"
                >
                  {listing.name}
                </Link>
              </h3>
              <p className="mt-1 text-sm text-zinc-400">
                <code className="font-mono">{listing.slug}</code> ·{" "}
                {listing.format} ·{" "}
                ${(listing.price_cents / 100).toFixed(2)}
              </p>
              <p className="mt-2 line-clamp-3 text-sm text-zinc-300">
                {listing.description_md.slice(0, 240)}
                {listing.description_md.length > 240 ? "…" : ""}
              </p>
              <p className="mt-2 text-xs text-zinc-500">
                seller: <span className="font-mono">{listing.seller_id}</span>
              </p>
              <Link
                href={`/admin/marketplace/listings/${listing.listing_id}`}
                className="mt-2 inline-block text-xs text-zinc-300 underline"
              >
                Open full review →
              </Link>
            </div>
            <ModerationActions
              listingId={listing.listing_id}
              listingName={listing.name}
              slug={listing.slug}
            />
          </li>
        ))}
      </ul>
    </div>
  );
}
