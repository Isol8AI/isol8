import { getListing } from "@/lib/api";
import { BuyButton } from "@/components/Listing/BuyButton";
import { MarkdownDescription } from "@/components/Listing/MarkdownDescription";
import type { ListingManifest } from "@/lib/types";
import { notFound } from "next/navigation";

export default async function ListingDetail({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  let detail;
  try {
    detail = await getListing(slug);
  } catch {
    detail = null;
  }
  if (!detail) notFound();
  const { listing, manifest } = detail;

  const isPaid = listing.price_cents > 0;

  return (
    <main className="max-w-4xl mx-auto px-6 py-12">
      <header className="mb-8">
        <span className="text-sm text-zinc-400 uppercase tracking-wider">
          {/* v0 only publishes openclaw, so this is always "Agent". */}
          Agent
        </span>
        <h1 className="text-4xl font-bold mt-2">
          {manifest?.emoji ? <span className="mr-2">{manifest.emoji}</span> : null}
          {listing.name}
        </h1>
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

      {manifest && <ManifestSummary manifest={manifest} />}

      <BuyButton listing={listing} />

      {isPaid && (
        <section className="mt-10 rounded-lg border border-zinc-800 p-5">
          <h2 className="text-lg font-semibold mb-3">After purchase</h2>
          <p className="text-sm text-zinc-400">
            After Stripe Checkout completes, your purchased agent will be
            deployed to your Isol8 container automatically. You&apos;ll be
            redirected to a confirmation page with a deep-link to open it in
            chat.
          </p>
        </section>
      )}
    </main>
  );
}

function ManifestSummary({ manifest }: { manifest: ListingManifest }) {
  const noneIfEmpty = (xs: string[] | undefined) =>
    xs && xs.length > 0 ? xs.join(", ") : "None";

  const identityBits: string[] = [];
  if (manifest.vibe) identityBits.push(manifest.vibe);
  else identityBits.push("an agent");
  if (manifest.suggested_model) identityBits.push(manifest.suggested_model);

  return (
    <section className="mb-10 rounded-lg border border-zinc-800 p-5">
      <h2 className="text-lg font-semibold mb-3">What&apos;s bundled</h2>
      <ul className="space-y-1.5 text-sm text-zinc-300">
        <li>
          <span className="text-zinc-500">Identity:</span>{" "}
          {identityBits.join(" — ")}
        </li>
        <li>
          <span className="text-zinc-500">Required skills:</span>{" "}
          {noneIfEmpty(manifest.required_skills)}
        </li>
        <li>
          <span className="text-zinc-500">Required plugins:</span>{" "}
          {noneIfEmpty(manifest.required_plugins)}
        </li>
        <li>
          <span className="text-zinc-500">Required tools:</span>{" "}
          {noneIfEmpty(manifest.required_tools)}
        </li>
        <li>
          <span className="text-zinc-500">Suggested channels:</span>{" "}
          {noneIfEmpty(manifest.suggested_channels)}
        </li>
      </ul>
      <p className="mt-4 text-xs text-zinc-500">
        Some skills referenced by this agent may not be bundled in the
        artifact. After deploy, your container&apos;s{" "}
        <code className="bg-zinc-900 px-1 py-0.5 rounded">openclaw.json</code>{" "}
        may need a manual entry registering the agent — openclaw-slice
        synthesis is not yet automated for marketplace publishes.
      </p>
    </section>
  );
}
