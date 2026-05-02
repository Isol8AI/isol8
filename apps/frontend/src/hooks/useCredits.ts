"use client";

import useSWR from "swr";
import { useApi } from "@/lib/api";

export type CreditsBalance = {
  balance_microcents: number;
  balance_dollars: string;
};

export type AutoReloadConfig = {
  enabled: boolean;
  threshold_cents?: number;
  amount_cents?: number;
};

export type TopUpResult = {
  /** Stripe-hosted Checkout URL — frontend should `window.location.href = checkout_url`. */
  checkout_url: string;
};

export function useCredits() {
  const api = useApi();

  const { data, error, mutate } = useSWR<CreditsBalance>(
    "/billing/credits/balance",
    (path: string) => api.get(path) as Promise<CreditsBalance>,
    {
      // Top-ups land via Stripe webhook, so revalidate quickly to surface the
      // new balance without forcing the user to refresh the page manually.
      refreshInterval: 30_000,
      revalidateOnFocus: true,
    },
  );

  const startTopUp = async (amountCents: number): Promise<TopUpResult> => {
    return (await api.post("/billing/credits/top_up", {
      amount_cents: amountCents,
    })) as TopUpResult;
  };

  const setAutoReload = async (params: AutoReloadConfig): Promise<void> => {
    await api.put("/billing/credits/auto_reload", params);
  };

  return {
    balance: data,
    isLoading: !data && !error,
    error,
    refresh: mutate,
    startTopUp,
    setAutoReload,
  };
}
