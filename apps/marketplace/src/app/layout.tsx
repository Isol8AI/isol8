import "./globals.css";
import {
  ClerkProvider,
  SignedIn,
  SignedOut,
  SignInButton,
  UserButton,
} from "@clerk/nextjs";
import Link from "next/link";

import { UserSync } from "@/components/UserSync";

export const metadata = {
  title: "marketplace.isol8.co — AI agents you can deploy in one click",
  description: "The marketplace for AI agents. Browse, buy, deploy into your Isol8 container.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <ClerkProvider>
      <html lang="en">
        <body className="bg-zinc-950 text-zinc-100 min-h-screen flex flex-col">
          <UserSync />
          <header className="border-b border-zinc-800">
            <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
              <Link href="/" className="text-lg font-semibold tracking-tight">
                isol8 marketplace
              </Link>
              <nav className="flex items-center gap-6 text-sm">
                <Link href="/agents" className="text-zinc-300 hover:text-zinc-100">
                  Browse
                </Link>
                <SignedIn>
                  <Link href="/buyer" className="text-zinc-300 hover:text-zinc-100">
                    Purchases
                  </Link>
                  <Link href="/dashboard" className="text-zinc-300 hover:text-zinc-100">
                    Earnings
                  </Link>
                  <UserButton afterSignOutUrl="/" />
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
              <span>marketplace.isol8.co · An Isol8 product</span>
              <div className="flex gap-4">
                <a href="https://isol8.co/terms" className="hover:text-zinc-300">
                  Terms
                </a>
                <a href="https://isol8.co/privacy" className="hover:text-zinc-300">
                  Privacy
                </a>
                <a href="https://isol8.co" className="hover:text-zinc-300">
                  isol8.co →
                </a>
              </div>
            </div>
          </footer>
        </body>
      </html>
    </ClerkProvider>
  );
}
