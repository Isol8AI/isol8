import Link from "next/link";
import type { Listing } from "@/lib/marketplace/types";

// Strip markdown noise for the card preview — full markdown render lives on
// the detail page. This keeps cards visually consistent (no headings/lists
// poking out) without dragging react-markdown into the home/browse bundle.
function stripMarkdown(md: string): string {
  return md
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`[^`]*`/g, " ")
    .replace(/!?\[([^\]]*)\]\([^)]+\)/g, "$1")
    .replace(/^[#>*\-+]+\s*/gm, "")
    .replace(/\*\*|__|\*|_/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

export function ListingCard({ listing }: { listing: Listing }) {
  const price = listing.price_cents === 0
    ? "Free"
    : `$${(listing.price_cents / 100).toFixed(2)}`;
  const preview = stripMarkdown(listing.description_md);
  return (
    <Link
      href={`/marketplace/listing/${listing.slug}`}
      className="block rounded-xl border border-zinc-800 p-5 hover:border-zinc-600 transition"
    >
      <div className="flex items-start justify-between mb-2">
        <h3 className="font-semibold text-lg text-zinc-100">{listing.name}</h3>
        <span className="text-sm text-zinc-400">{price}</span>
      </div>
      <p className="text-sm text-zinc-400 mb-3 line-clamp-2">{preview}</p>
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
