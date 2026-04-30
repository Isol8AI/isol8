import Link from "next/link";
import type { Listing } from "@isol8/marketplace-shared";

export function ListingCard({ listing }: { listing: Listing }) {
  const price = listing.price_cents === 0
    ? "Free"
    : `$${(listing.price_cents / 100).toFixed(2)}`;
  return (
    <Link
      href={`/listing/${listing.slug}`}
      className="block rounded-xl border border-zinc-800 p-5 hover:border-zinc-600 transition"
    >
      <div className="flex items-start justify-between mb-2">
        <h3 className="font-semibold text-lg text-zinc-100">{listing.name}</h3>
        <span className="text-sm text-zinc-400">{price}</span>
      </div>
      <p className="text-sm text-zinc-400 mb-3 line-clamp-2">{listing.description_md}</p>
      <div className="flex flex-wrap gap-1">
        {listing.tags.map((t) => (
          <span key={t} className="text-xs px-2 py-0.5 rounded bg-zinc-800 text-zinc-300">
            {t}
          </span>
        ))}
      </div>
    </Link>
  );
}
