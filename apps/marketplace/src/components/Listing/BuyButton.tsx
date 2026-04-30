"use client";
import type { Listing } from "@isol8/marketplace-shared";
import { useAuth, useUser } from "@clerk/nextjs";
import { useState } from "react";

export function BuyButton({ listing }: { listing: Listing }) {
  const { isSignedIn, getToken } = useAuth();
  const { user } = useUser();
  const [loading, setLoading] = useState(false);

  if (listing.price_cents === 0) {
    const cmd = `npx @isol8/marketplace install ${listing.slug}`;
    return (
      <div className="rounded-lg border border-zinc-700 p-6">
        <h3 className="font-semibold mb-3">Install (free)</h3>
        <pre className="bg-zinc-900 px-4 py-3 rounded overflow-x-auto text-sm">{cmd}</pre>
        <p className="text-sm text-zinc-400 mt-3">
          Auto-detects Claude Code, Cursor, OpenClaw, Copilot CLI.
        </p>
      </div>
    );
  }

  async function purchase() {
    if (!isSignedIn) {
      window.location.href = `/sign-in?redirect_url=${encodeURIComponent(window.location.href)}`;
      return;
    }
    setLoading(true);
    const jwt = await getToken();
    const resp = await fetch("/api/internal/checkout", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        listing_slug: listing.slug,
        jwt,
        email: user?.primaryEmailAddress?.emailAddress,
      }),
    });
    const body = await resp.json();
    if (body.checkout_url) {
      window.location.href = body.checkout_url;
    } else {
      setLoading(false);
      alert(`Checkout failed: ${body.error ?? "unknown"}`);
    }
  }

  const price = `$${(listing.price_cents / 100).toFixed(2)}`;
  return (
    <button
      onClick={purchase}
      disabled={loading}
      className="px-6 py-3 bg-zinc-100 text-zinc-950 rounded-lg font-semibold disabled:opacity-50"
    >
      {loading ? "Loading..." : `Buy for ${price}`}
    </button>
  );
}
