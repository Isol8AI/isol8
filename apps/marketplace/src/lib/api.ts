import type { Listing } from "@isol8/marketplace-shared";

const API = process.env.NEXT_PUBLIC_API_URL ?? "https://api.isol8.co";

export async function browseListings(opts: {
  tags?: string;
  limit?: number;
  format?: "openclaw" | "skillmd";
} = {}) {
  const params = new URLSearchParams();
  if (opts.tags) params.set("tags", opts.tags);
  if (opts.limit) params.set("limit", String(opts.limit));
  if (opts.format) params.set("format", opts.format);
  const resp = await fetch(`${API}/api/v1/marketplace/listings?${params}`, {
    next: { revalidate: 60 },
  });
  if (!resp.ok) throw new Error(`browseListings failed: ${resp.status}`);
  const body = (await resp.json()) as { items: Listing[]; count: number };
  return body;
}

export async function getListing(slug: string): Promise<Listing | null> {
  const resp = await fetch(`${API}/api/v1/marketplace/listings/${encodeURIComponent(slug)}`, {
    next: { revalidate: 60 },
  });
  if (resp.status === 404) return null;
  if (!resp.ok) throw new Error(`getListing failed: ${resp.status}`);
  return resp.json();
}

export async function checkout(opts: {
  listingSlug: string;
  successUrl: string;
  cancelUrl: string;
  jwt: string;
  email?: string;
}) {
  const resp = await fetch(`${API}/api/v1/marketplace/checkout`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      Authorization: `Bearer ${opts.jwt}`,
    },
    body: JSON.stringify({
      listing_slug: opts.listingSlug,
      success_url: opts.successUrl,
      cancel_url: opts.cancelUrl,
      email: opts.email,
    }),
  });
  if (!resp.ok) throw new Error(`checkout failed: ${resp.status}`);
  return (await resp.json()) as { checkout_url: string; session_id: string };
}
