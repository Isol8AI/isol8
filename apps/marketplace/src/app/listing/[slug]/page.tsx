import { getListing } from "@/lib/api";
import { BuyButton } from "@/components/Listing/BuyButton";
import { MarkdownDescription } from "@/components/Listing/MarkdownDescription";
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

  const isPaid = listing.price_cents > 0;

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

      <article className="mb-12 text-zinc-300">
        <MarkdownDescription source={listing.description_md} />
      </article>

      <BuyButton listing={listing} />

      {isPaid && (
        <section className="mt-10 rounded-lg border border-zinc-800 p-5">
          <h2 className="text-lg font-semibold mb-3">After purchase</h2>
          <ol className="list-decimal pl-5 space-y-2 text-sm text-zinc-400">
            <li>
              Stripe checkout completes; you&apos;ll see a license key on{" "}
              <code>/buyer</code>.
            </li>
            <li>
              Run{" "}
              <code className="bg-zinc-900 px-2 py-0.5 rounded">
                npx @isol8/marketplace install {listing.slug}
              </code>{" "}
              and follow the browser handoff.
            </li>
            <li>
              The skill lands at{" "}
              <code>~/.claude/skills/{listing.slug}/</code> (auto-detected for
              Cursor / OpenClaw / Copilot too).
            </li>
          </ol>
        </section>
      )}
    </main>
  );
}
