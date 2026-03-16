"use client";

import { useCallback } from "react";
import useSWR from "swr";
import { useAuth } from "@clerk/nextjs";
import { BACKEND_URL } from "@/lib/api";

interface UsagePeriod {
  start: string;
  end: string;
  included_budget: number;
  used: number;
  overage: number;
  percent_used: number;
}

interface BillingAccount {
  plan_tier: string;
  has_subscription: boolean;
  current_period: UsagePeriod;
}

export function useBilling() {
  const { getToken, isSignedIn } = useAuth();

  const fetcher = useCallback(
    async (url: string) => {
      const token = await getToken();
      if (!token) throw new Error("No auth token");

      const res = await fetch(`${BACKEND_URL}${url}`, {
        headers: { Authorization: `Bearer ${token}` },
      });

      if (res.status === 404) return null;
      if (!res.ok) throw new Error("Failed to fetch billing account");
      return res.json();
    },
    [getToken],
  );

  const { data, error, isLoading, mutate } = useSWR<BillingAccount | null>(
    isSignedIn ? "/billing/account" : null,
    fetcher,
    {
      revalidateOnFocus: false,
      dedupingInterval: 30000,
    },
  );

  const createCheckout = useCallback(
    async (tier: "starter" | "pro") => {
      const token = await getToken();
      if (!token) throw new Error("No auth token");

      const res = await fetch(`${BACKEND_URL}/billing/checkout`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ tier }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to create checkout session");
      }

      const { checkout_url } = await res.json();
      window.location.href = checkout_url;
    },
    [getToken],
  );

  const openPortal = useCallback(async () => {
    const token = await getToken();
    if (!token) throw new Error("No auth token");

    const res = await fetch(`${BACKEND_URL}/billing/portal`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
    });

    if (!res.ok) throw new Error("Failed to create portal session");

    const { portal_url } = await res.json();
    window.location.href = portal_url;
  }, [getToken]);

  const isSubscribed = data?.has_subscription === true;
  const planTier = data?.plan_tier ?? "free";
  const refresh = useCallback(() => mutate(), [mutate]);

  return {
    account: data,
    isLoading,
    error,
    isSubscribed,
    planTier,
    createCheckout,
    openPortal,
    refresh,
  };
}
