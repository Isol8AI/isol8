import { getListing } from "@/lib/api";
import { BuyButton } from "@/components/Listing/BuyButton";
import { notFound } from "next/navigation";

export default async function ListingDetail({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  let listing;
  try {
    listing = await getListing(slug);
  } catch {
    listing = null;
  }
  if (!listing) notFound();
  return (
    <main className="max-w-4xl mx-auto px-6 py-12">
      <header className="mb-8">
        <span className="text-sm text-zinc-400 uppercase tracking-wider">
          {listing.format === "openclaw" ? "Agent" : "Skill"}
        </span>
        <h1 className="text-4xl font-bold mt-2">{listing.name}</h1>
        <div className="flex gap-2 mt-3">
          {listing.tags.map((t) => (
            <span key={t} className="text-xs px-2 py-1 bg-zinc-800 rounded">
              {t}
            </span>
          ))}
        </div>
      </header>
      <article className="prose prose-invert max-w-none mb-12">
        <p className="whitespace-pre-line text-zinc-300">{listing.description_md}</p>
      </article>
      <BuyButton listing={listing} />
    </main>
  );
}
