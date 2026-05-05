import { SignedIn, SignedOut, SignInButton, UserButton } from "@clerk/nextjs";
import Link from "next/link";
import type { Metadata } from "next";

import { UserSync } from "@/components/marketplace/storefront/UserSync";

// Nested layout: the root <html>/<body> + ClerkProvider live in
// apps/frontend/src/app/layout.tsx. This wraps just the /marketplace/*
// subtree with the storefront chrome (header + footer). Internal nav
// links use /marketplace/... paths because we run path-based, not
// host-based, routing — buyers see isol8.co/marketplace/agents, not
// marketplace.isol8.co/agents.
export const metadata: Metadata = {
  title: "Isol8 Marketplace — AI agents you can deploy in one click",
  description: "Browse, buy, and deploy AI agents into your Isol8 container.",
};

export default function MarketplaceLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="bg-zinc-950 text-zinc-100 min-h-screen flex flex-col">
      <UserSync />
      <header className="border-b border-zinc-800">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
          <Link href="/marketplace" className="text-lg font-semibold tracking-tight">
            isol8 marketplace
          </Link>
          <nav className="flex items-center gap-6 text-sm">
            <Link href="/marketplace/agents" className="text-zinc-300 hover:text-zinc-100">
              Browse
            </Link>
            <SignedIn>
              <Link href="/marketplace/buyer" className="text-zinc-300 hover:text-zinc-100">
                Purchases
              </Link>
              <Link href="/marketplace/dashboard" className="text-zinc-300 hover:text-zinc-100">
                Earnings
              </Link>
              <UserButton afterSignOutUrl="/marketplace" />
            </SignedIn>
            <SignedOut>
              <SignInButton mode="modal">
                <button
                  type="button"
                  className="px-3 py-1.5 rounded bg-zinc-100 text-zinc-950 font-medium text-sm"
                >
                  Sign in
                </button>
              </SignInButton>
            </SignedOut>
          </nav>
        </div>
      </header>
      <div className="flex-1">{children}</div>
      <footer className="border-t border-zinc-800 mt-16">
        <div className="max-w-6xl mx-auto px-6 py-6 flex items-center justify-between text-xs text-zinc-500">
          <span>Isol8 Marketplace · part of isol8.co</span>
          <div className="flex gap-4">
            <Link href="/terms" className="hover:text-zinc-300">
              Terms
            </Link>
            <Link href="/privacy" className="hover:text-zinc-300">
              Privacy
            </Link>
            <Link href="/" className="hover:text-zinc-300">
              ← isol8.co
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
