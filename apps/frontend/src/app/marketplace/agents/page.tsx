import { browseListings } from "@/lib/marketplace/api";
import { ListingCard } from "@/components/marketplace/storefront/Listing/ListingCard";

export default async function Agents() {
  let items: Awaited<ReturnType<typeof browseListings>>["items"] = [];
  try {
    const result = await browseListings({ format: "openclaw", limit: 50 });
    items = result.items;
  } catch {
    // Best-effort during local dev.
  }
  return (
    <main className="max-w-6xl mx-auto px-6 py-12">
      <h1 className="text-3xl font-bold mb-6">Browse agents</h1>
      {items.length === 0 ? (
        <p className="text-zinc-400">No agents listed yet.</p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {items.map((a) => (
            <ListingCard key={a.listing_id} listing={a} />
          ))}
        </div>
      )}
    </main>
  );
}
