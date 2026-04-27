"use client";

import { useSyncExternalStore } from "react";
import useSWR from "swr";
import Link from "next/link";
import { useApi } from "@/lib/api";

// Subscribe to a 60-second clock tick. useSyncExternalStore is the
// React 19 idiomatic way to expose mutable external state (current time)
// without tripping the no-impure-during-render or set-state-in-effect
// lint rules.
function subscribeToMinute(onChange: () => void): () => void {
  const t = setInterval(onChange, 60_000);
  return () => clearInterval(t);
}
function getNow(): number {
  return Date.now();
}
function getServerNow(): number {
  // SSR snapshot — return 0 so the banner renders nothing on the server
  // pass and lights up after hydration.
  return 0;
}

// The /billing/account response does not currently surface
// subscription_status / trial_end (the BillingAccountResponse pydantic
// schema strips them), but the underlying DynamoDB row stores both
// (set by the trial_will_end + customer.subscription.updated webhook
// branches landed in Plan 3 Task 2). When the response model is
// extended to include these fields, this banner lights up
// automatically — until then, the trialing condition just never
// matches and the banner stays hidden.
type BillingAccount = {
  subscription_status?: string;
  trial_end?: number; // Unix seconds
};

export function TrialBanner() {
  const api = useApi();
  const { data } = useSWR<BillingAccount | null>(
    "/billing/account",
    (path: string) => api.get(path) as Promise<BillingAccount | null>,
    { refreshInterval: 60_000 },
  );

  const now = useSyncExternalStore(subscribeToMinute, getNow, getServerNow);

  if (
    !data ||
    data.subscription_status !== "trialing" ||
    !data.trial_end ||
    now === 0
  ) {
    return null;
  }
  const daysLeft = Math.max(
    0,
    Math.ceil((data.trial_end * 1000 - now) / 86_400_000),
  );
  const chargeDate = new Date(data.trial_end * 1000).toLocaleDateString();

  return (
    <div className="bg-primary/10 border-b border-primary/20 px-4 py-2 text-sm flex items-center justify-between">
      <span>
        Your free trial ends in{" "}
        <strong>
          {daysLeft} day{daysLeft === 1 ? "" : "s"}
        </strong>
        . You&apos;ll be charged $50 on {chargeDate}.
      </span>
      <Link href="/settings?panel=billing" className="text-primary underline">
        Manage
      </Link>
    </div>
  );
}
