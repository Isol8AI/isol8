"use client";

import { useCallback } from "react";
import useSWR from "swr";
import { useAuth } from "@clerk/nextjs";
import { BACKEND_URL } from "@/lib/api";

// =============================================================================
// Flat-fee billing hook. Backend response shapes match
// apps/backend/schemas/billing.py.
// =============================================================================

export interface BillingAccount {
  is_subscribed: boolean;
  current_spend: number;
  lifetime_spend: number;
  // Stripe-native subscription state. Both null until the user signs up.
  subscription_status: string | null;
  trial_end: number | null;
}

export interface MemberUsage {
  user_id: string;
  display_name: string | null;
  email: string | null;
  total_spend: number;
  total_input_tokens: number;
  total_output_tokens: number;
  request_count: number;
}

export interface UsageSummary {
  period: string;
  total_spend: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_cache_read_tokens: number;
  total_cache_write_tokens: number;
  request_count: number;
  lifetime_spend: number;
  by_member: MemberUsage[];
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
      if (!res.ok) throw new Error("Failed to fetch billing data");
      return res.json();
    },
    [getToken],
  );

  const {
    data: account,
    error,
    isLoading,
    mutate,
  } = useSWR<BillingAccount | null>(
    isSignedIn ? "/billing/account" : null,
    fetcher,
    {
      revalidateOnFocus: false,
      dedupingInterval: 30000,
    },
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

  const fetchUsage = useCallback(async (): Promise<UsageSummary | null> => {
    const token = await getToken();
    if (!token) throw new Error("No auth token");

    const res = await fetch(`${BACKEND_URL}/billing/usage`, {
      headers: { Authorization: `Bearer ${token}` },
    });

    if (res.status === 404) return null;
    if (!res.ok) throw new Error("Failed to fetch usage data");
    return res.json();
  }, [getToken]);

  const isSubscribed = account?.is_subscribed === true;
  const refresh = useCallback(() => mutate(), [mutate]);

  return {
    account,
    isLoading,
    error,
    isSubscribed,
    openPortal,
    fetchUsage,
    refresh,
  };
}
