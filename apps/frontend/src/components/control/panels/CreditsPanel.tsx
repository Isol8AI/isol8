"use client";

import { useState } from "react";
import { useCredits } from "@/hooks/useCredits";

export function CreditsPanel() {
  const { balance, startTopUp, setAutoReload, refresh } = useCredits();
  const [topUpAmount, setTopUpAmount] = useState(2000);
  const [autoEnabled, setAutoEnabled] = useState(false);
  const [threshold, setThreshold] = useState(500);
  const [reloadAmount, setReloadAmount] = useState(2000);
  const [pendingTopUpSecret, setPendingTopUpSecret] = useState<string | null>(
    null,
  );

  const handleTopUp = async () => {
    const r = await startTopUp(topUpAmount);
    setPendingTopUpSecret(r.client_secret);
    // Frontend would normally hand this off to Stripe Elements; for now,
    // the panel surfaces the client_secret so the user can complete in
    // the onboarding-style CreditsStep flow. Wire up a full in-panel
    // Elements flow in a follow-up task.
    refresh();
  };

  const handleAutoReloadSave = async () => {
    await setAutoReload({
      enabled: autoEnabled,
      threshold_cents: autoEnabled ? threshold : undefined,
      amount_cents: autoEnabled ? reloadAmount : undefined,
    });
  };

  return (
    <div className="p-6 space-y-8">
      <h2 className="text-xl font-semibold">Claude credits</h2>

      <section>
        <div className="text-3xl font-bold">
          {balance ? `$${balance.balance_dollars}` : "$0.00"}
        </div>
        <div className="text-xs text-muted-foreground">Current balance</div>
      </section>

      <section className="space-y-2">
        <h3 className="text-sm font-semibold">Add credits</h3>
        <div className="flex gap-2">
          {[1000, 2000, 5000, 10000].map((c) => (
            <button
              key={c}
              onClick={() => setTopUpAmount(c)}
              className={
                "rounded-md border px-3 py-1.5 text-sm " +
                (topUpAmount === c
                  ? "border-primary bg-primary/10"
                  : "border-border")
              }
            >
              ${c / 100}
            </button>
          ))}
        </div>
        <button
          onClick={handleTopUp}
          className="rounded-md bg-primary px-4 py-2 text-primary-foreground text-sm"
        >
          Add ${topUpAmount / 100}
        </button>
        {pendingTopUpSecret && (
          <p className="text-xs text-muted-foreground">
            Top-up initiated. Client secret: {pendingTopUpSecret.slice(0, 24)}…
            (Stripe Elements UI in a follow-up — for now, complete via the
            onboarding wizard.)
          </p>
        )}
      </section>

      <section className="space-y-2">
        <h3 className="text-sm font-semibold">Auto-reload</h3>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={autoEnabled}
            onChange={(e) => setAutoEnabled(e.target.checked)}
          />
          Enabled
        </label>
        {autoEnabled && (
          <div className="space-y-2 text-sm">
            <label className="block">
              When balance drops below:
              <input
                type="number"
                min={5}
                step={5}
                value={threshold / 100}
                onChange={(e) =>
                  setThreshold(Math.round(Number(e.target.value) * 100))
                }
                className="ml-2 w-24 rounded-md border border-input px-2 py-1"
              />
            </label>
            <label className="block">
              Charge me:
              <input
                type="number"
                min={5}
                step={5}
                value={reloadAmount / 100}
                onChange={(e) =>
                  setReloadAmount(Math.round(Number(e.target.value) * 100))
                }
                className="ml-2 w-24 rounded-md border border-input px-2 py-1"
              />
            </label>
          </div>
        )}
        <button
          onClick={handleAutoReloadSave}
          className="rounded-md bg-secondary px-4 py-2 text-sm"
        >
          Save
        </button>
      </section>
    </div>
  );
}
