"use client";
import { useMemo, useState } from "react";
import {
  Elements,
  PaymentElement,
  useElements,
  useStripe,
} from "@stripe/react-stripe-js";
import { loadStripe } from "@stripe/stripe-js";
import { useCredits } from "@/hooks/useCredits";

type Props = { onComplete: () => void };

const STRIPE_PUBLISHABLE_KEY =
  process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY ?? "";

const stripePromise = STRIPE_PUBLISHABLE_KEY
  ? loadStripe(STRIPE_PUBLISHABLE_KEY)
  : null;

const PRESET_AMOUNTS_CENTS = [1000, 2000, 5000, 10000]; // $10, $20, $50, $100

export function CreditsStep({ onComplete }: Props) {
  const { startTopUp } = useCredits();
  const [amount, setAmount] = useState<number>(2000);
  const [clientSecret, setClientSecret] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const beginCheckout = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const r = await startTopUp(amount);
      setClientSecret(r.client_secret);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to start checkout");
    } finally {
      setSubmitting(false);
    }
  };

  const options = useMemo(
    () => (clientSecret ? { clientSecret } : null),
    [clientSecret],
  );

  if (!stripePromise) {
    return (
      <p className="py-8 text-sm text-destructive text-center">
        NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY is not configured.
      </p>
    );
  }

  if (clientSecret && options) {
    return (
      <Elements stripe={stripePromise} options={options}>
        <PaymentForm onSuccess={onComplete} amount={amount} />
      </Elements>
    );
  }

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
        onChange={(e) =>
          setAmount(Math.round(Number(e.target.value) * 100))
        }
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

function PaymentForm({
  onSuccess,
  amount,
}: {
  onSuccess: () => void;
  amount: number;
}) {
  const stripe = useStripe();
  const elements = useElements();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!stripe || !elements) return;
    setSubmitting(true);
    setError(null);
    const { error: stripeError } = await stripe.confirmPayment({
      elements,
      confirmParams: { return_url: window.location.href },
      redirect: "if_required",
    });
    if (stripeError) {
      setError(stripeError.message ?? "Payment failed");
      setSubmitting(false);
      return;
    }
    // Webhook will credit the balance asynchronously; advance the wizard.
    onSuccess();
  };

  return (
    <form
      onSubmit={submit}
      className="flex flex-col gap-4 py-8 max-w-md mx-auto"
    >
      <h3 className="text-xl font-semibold">Pay ${amount / 100}</h3>
      <PaymentElement />
      {error && <p className="text-sm text-destructive">{error}</p>}
      <button
        type="submit"
        disabled={!stripe || submitting}
        className="rounded-md bg-primary px-4 py-2 text-primary-foreground disabled:opacity-50"
      >
        {submitting ? "Processing…" : `Pay $${amount / 100}`}
      </button>
    </form>
  );
}
