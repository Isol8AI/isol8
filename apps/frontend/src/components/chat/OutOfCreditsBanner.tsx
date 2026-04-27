"use client";

import Link from "next/link";
import { useCredits } from "@/hooks/useCredits";

export function OutOfCreditsBanner() {
  const { balance } = useCredits();
  if (!balance || balance.balance_microcents > 0) return null;

  return (
    <div className="bg-destructive/10 border-b border-destructive/20 px-4 py-2 text-sm flex items-center justify-between">
      <span className="text-destructive">
        You&apos;re out of Claude credits. Top up to keep chatting.
      </span>
      <Link
        href="/settings/credits"
        className="rounded-md bg-destructive px-3 py-1 text-destructive-foreground text-xs"
      >
        Top up now
      </Link>
    </div>
  );
}
