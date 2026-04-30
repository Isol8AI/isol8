import { browseListings } from "@/lib/api";
import { ListingCard } from "@/components/Listing/ListingCard";
import Link from "next/link";

export default async function Home() {
  let agents: Awaited<ReturnType<typeof browseListings>>["items"] = [];
  try {
    const result = await browseListings({ format: "openclaw", limit: 8 });
    agents = result.items;
  } catch {
    // Backend may be unavailable during local dev; render the home page
    // shell with no featured agents rather than 500ing.
  }
  return (
    <main className="max-w-6xl mx-auto px-6 py-16">
      <section className="mb-16">
        <h1 className="text-5xl font-bold mb-4">The marketplace for AI agents.</h1>
        <p className="text-xl text-zinc-400 mb-8 max-w-2xl">
          Complete AI workers with identity, workflows, and skills. Deploy in one command.
        </p>
        <div className="flex gap-4">
          <Link
            href="/agents"
            className="px-6 py-3 bg-zinc-100 text-zinc-950 rounded-lg font-semibold"
          >
            Browse agents
          </Link>
          <Link href="/sell" className="px-6 py-3 border border-zinc-700 rounded-lg">
            Sell yours
          </Link>
        </div>
      </section>
      <section>
        <div className="flex justify-between items-baseline mb-6">
          <h2 className="text-2xl font-semibold">Featured agents</h2>
          <Link href="/agents" className="text-sm text-zinc-400 hover:text-zinc-100">
            View all →
          </Link>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {agents.map((a) => (
            <ListingCard key={a.listing_id} listing={a} />
          ))}
        </div>
      </section>
    </main>
  );
}
