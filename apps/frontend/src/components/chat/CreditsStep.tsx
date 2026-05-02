"use client";
import { useEffect, useRef, useState } from "react";
import { useApi } from "@/lib/api";
import { useCredits } from "@/hooks/useCredits";

type Props = { onComplete: () => void };

const PRESET_AMOUNTS_CENTS = [1000, 2000, 5000, 10000]; // $10, $20, $50, $100

/**
 * Bedrock onboarding step: collect an initial Claude credit top-up via
 * Stripe Checkout. Replaces the previous inline-Elements implementation
 * (which required NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY and didn't support
 * Stripe coupons) with a single button → server-rendered Checkout page.
 *
 * Stripe Checkout is a full-page redirect, so the in-flight Promise
 * doesn't get to call `onComplete` itself. Instead, when the user
 * returns to /chat the credit balance refresh (via useCredits) flips
 * positive and we auto-advance the wizard. ChatLayout already strips
 * the ?credits= param so the URL stays clean.
 */
export function CreditsStep({ onComplete }: Props) {
  const api = useApi();
  const { balance, refresh } = useCredits();
  const [amount, setAmount] = useState<number>(2000);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const advancedRef = useRef(false);

  // On mount and on every balance bump, check whether we already have
  // credits — if so, the user is returning from a successful Checkout
  // (or arrived here with a pre-existing balance) and the wizard should
  // skip past the top-up step.
  useEffect(() => {
    if (advancedRef.current) return;
    if (balance && balance.balance_microcents > 0) {
      advancedRef.current = true;
      onComplete();
    }
  }, [balance, onComplete]);

  // Force a balance refresh on mount so we don't wait the SWR refresh
  // interval to detect the post-Checkout webhook landing.
  useEffect(() => {
    void refresh();
  }, [refresh]);

  const beginCheckout = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const r = (await api.post("/billing/credits/top_up", {
        amount_cents: amount,
      })) as { checkout_url?: string };
      if (!r?.checkout_url) throw new Error("No checkout_url returned");
      window.location.href = r.checkout_url;
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to start checkout");
      setSubmitting(false);
    }
  };

  return (
    <div className="flex flex-col gap-4 py-8 max-w-md mx-auto">
      <h3 className="text-xl font-semibold">Add Claude credits</h3>
      <p className="text-sm text-muted-foreground">
        Prepay for Claude inference. Credits are deducted as you chat
        (1.4&times; the raw cost). Add any amount, top up later anytime.
      </p>

      <div className="grid grid-cols-4 gap-2">
        {PRESET_AMOUNTS_CENTS.map((c) => (
          <button
            key={c}
            type="button"
            onClick={() => setAmount(c)}
            className={
              "rounded-md border px-3 py-2 text-sm " +
              (amount === c
                ? "border-primary bg-primary/10"
                : "border-border bg-card")
            }
          >
            ${c / 100}
          </button>
        ))}
      </div>

      <input
        type="number"
        min={5}
        step={5}
        value={amount / 100}
        onChange={(e) => setAmount(Math.round(Number(e.target.value) * 100))}
        className="rounded-md border border-input bg-background px-3 py-2"
      />

      {error && <p className="text-sm text-destructive">{error}</p>}

      <button
        onClick={beginCheckout}
        disabled={submitting || amount < 500}
        className="rounded-md bg-primary px-4 py-2 text-primary-foreground disabled:opacity-50"
      >
        {submitting ? "Loading…" : `Add $${amount / 100}`}
      </button>
    </div>
  );
}
