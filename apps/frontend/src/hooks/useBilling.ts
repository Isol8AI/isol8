"use client";

import { useCallback } from "react";
import useSWR from "swr";
import { useAuth } from "@clerk/nextjs";
import { BACKEND_URL } from "@/lib/api";

// =============================================================================
// Types matching new backend API response shapes
// =============================================================================

export interface BillingAccount {
  tier: string;
  is_subscribed: boolean;
  current_spend: number;
  included_budget: number;
  lifetime_spend: number;
  overage_enabled: boolean;
  overage_limit: number | null;
  within_included: boolean;
}

export interface MemberUsage {
  user_id: string;
  email?: string;
  name?: string;
  total_spend: number;
  request_count: number;
}

export interface UsageSummary {
  period: { start: string; end: string };
  total_spend: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_cache_read_tokens: number;
  total_cache_write_tokens: number;
  request_count: number;
  lifetime_spend: number;
  by_member: MemberUsage[];
}

export interface PricingInfo {
  models: Record<string, { input: number; output: number }>;
  markup: number;
  tier_model: string;
  subagent_model: string;
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

  const fetchPricing = useCallback(async (): Promise<PricingInfo | null> => {
    const token = await getToken();
    if (!token) throw new Error("No auth token");

    const res = await fetch(`${BACKEND_URL}/billing/pricing`, {
      headers: { Authorization: `Bearer ${token}` },
    });

    if (res.status === 404) return null;
    if (!res.ok) throw new Error("Failed to fetch pricing data");
    return res.json();
  }, [getToken]);

  const toggleOverage = useCallback(
    async (enabled: boolean, limitDollars?: number | null) => {
      const token = await getToken();
      if (!token) throw new Error("No auth token");

      const res = await fetch(`${BACKEND_URL}/billing/overage`, {
        method: "PUT",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          enabled,
          limit_dollars: limitDollars ?? null,
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to update overage settings");
      }

      // Refresh account data after toggling overage
      mutate();
      return res.json();
    },
    [getToken, mutate],
  );

  const isSubscribed = account?.is_subscribed === true;
  const planTier = account?.tier ?? "free";
  const refresh = useCallback(() => mutate(), [mutate]);

  return {
    account,
    isLoading,
    error,
    isSubscribed,
    planTier,
    createCheckout,
    openPortal,
    fetchUsage,
    fetchPricing,
    toggleOverage,
    refresh,
  };
}
