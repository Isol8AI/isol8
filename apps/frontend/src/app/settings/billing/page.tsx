"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Loader2,
  CreditCard,
  ExternalLink,
  Check,
  AlertCircle,
  Shield,
  Zap,
  Crown,
} from "lucide-react";
import { useOrganization } from "@clerk/nextjs";
import { useBilling } from "@/hooks/useBilling";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

// =============================================================================
// Constants
// =============================================================================

const PLAN_TIERS = [
  {
    id: "free" as const,
    name: "Free",
    price: 0,
    budget: 2,
    icon: Shield,
    features: [
      "1 personal pod",
      "Persistent memory & personality",
      "Core skills included",
      "$2 included usage budget",
    ],
  },
  {
    id: "starter" as const,
    name: "Starter",
    price: 25,
    budget: 25,
    icon: Zap,
    features: [
      "1 personal pod",
      "Persistent memory & personality",
      "Core skills included",
      "Pay-per-use premium models",
      "$25 included usage budget",
      "Standard support",
    ],
  },
  {
    id: "pro" as const,
    name: "Pro",
    price: 75,
    budget: 75,
    icon: Crown,
    popular: true,
    features: [
      "Everything in Starter",
      "Higher usage budget",
      "All premium skills & tools",
      "All top-tier models",
      "$75 included usage budget",
      "Priority support",
    ],
  },
];

// =============================================================================
// Helpers
// =============================================================================

function formatDollars(amount: number, decimals = 2): string {
  return `$${amount.toFixed(decimals)}`;
}

// =============================================================================
// Component
// =============================================================================

export default function BillingPage() {
  const {
    account,
    isLoading,
    error: accountError,
    isSubscribed,
    planTier,
    createCheckout,
    openPortal,
    toggleOverage,
  } = useBilling();
  const { membership } = useOrganization();

  const isOrgAdmin = !membership || membership.role === "org:admin";

  // Overage controls
  const [overageEnabled, setOverageEnabled] = useState(false);
  const [overageLimit, setOverageLimit] = useState<string>("");
  const [overageSaving, setOverageSaving] = useState(false);
  const [overageError, setOverageError] = useState<string | null>(null);
  const [overageSuccess, setOverageSuccess] = useState(false);

  // Checkout loading
  const [checkoutLoading, setCheckoutLoading] = useState<string | null>(null);
  const [portalLoading, setPortalLoading] = useState(false);

  // Sync overage state from account
  useEffect(() => {
    if (account) {
      setOverageEnabled(account.overage_enabled);
      setOverageLimit(
        account.overage_limit != null ? String(account.overage_limit) : "",
      );
    }
  }, [account]);

  const handleCheckout = useCallback(
    async (tier: "starter" | "pro") => {
      setCheckoutLoading(tier);
      try {
        await createCheckout(tier);
      } catch {
        setCheckoutLoading(null);
      }
    },
    [createCheckout],
  );

  const handlePortal = useCallback(async () => {
    setPortalLoading(true);
    try {
      await openPortal();
    } catch {
      setPortalLoading(false);
    }
  }, [openPortal]);

  const handleOverageToggle = useCallback(async () => {
    const newEnabled = !overageEnabled;
    setOverageSaving(true);
    setOverageError(null);
    setOverageSuccess(false);
    try {
      const limit = overageLimit ? parseFloat(overageLimit) : null;
      await toggleOverage(newEnabled, limit);
      setOverageEnabled(newEnabled);
      setOverageSuccess(true);
      setTimeout(() => setOverageSuccess(false), 2000);
    } catch (err) {
      setOverageError(
        err instanceof Error ? err.message : "Failed to update overage",
      );
    } finally {
      setOverageSaving(false);
    }
  }, [overageEnabled, overageLimit, toggleOverage]);

  const handleOverageLimitSave = useCallback(async () => {
    setOverageSaving(true);
    setOverageError(null);
    setOverageSuccess(false);
    try {
      const limit = overageLimit ? parseFloat(overageLimit) : null;
      await toggleOverage(overageEnabled, limit);
      setOverageSuccess(true);
      setTimeout(() => setOverageSuccess(false), 2000);
    } catch (err) {
      setOverageError(
        err instanceof Error ? err.message : "Failed to update overage limit",
      );
    } finally {
      setOverageSaving(false);
    }
  }, [overageEnabled, overageLimit, toggleOverage]);

  // --- Loading state ---
  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  // --- Org member (non-admin) ---
  if (membership && membership.role !== "org:admin") {
    return (
      <div className="min-h-screen flex items-center justify-center px-4">
        <div className="max-w-md text-center space-y-4">
          <Shield className="h-12 w-12 text-muted-foreground mx-auto" />
          <h1 className="text-xl font-semibold">Billing restricted</h1>
          <p className="text-sm text-muted-foreground">
            Contact your organization admin to manage billing and subscription
            settings.
          </p>
        </div>
      </div>
    );
  }

  const currentSpend = account?.current_spend ?? 0;
  const includedBudget = account?.included_budget ?? 0;
  const budgetPercent =
    includedBudget > 0 ? (currentSpend / includedBudget) * 100 : 0;
  const isPaid = planTier === "starter" || planTier === "pro";

  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-3xl mx-auto px-4 py-12 space-y-8">
        {/* Page header */}
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Billing</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Manage your plan, payment method, and usage budget.
          </p>
        </div>

        {accountError && (
          <div className="flex items-center gap-2 px-4 py-3 rounded-lg bg-destructive/5 border border-destructive/20">
            <AlertCircle className="h-4 w-4 text-destructive flex-shrink-0" />
            <span className="text-sm text-destructive">
              Failed to load billing data. Please refresh the page.
            </span>
          </div>
        )}

        {/* ================================================================= */}
        {/* Current Plan Card                                                  */}
        {/* ================================================================= */}
        {account && (
          <div className="rounded-xl border border-border p-6 space-y-5">
            <div className="flex items-center justify-between">
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <h2 className="text-lg font-semibold capitalize">
                    {planTier} plan
                  </h2>
                  {isSubscribed && (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-600 text-xs font-medium">
                      <Check className="h-3 w-3" />
                      Active
                    </span>
                  )}
                </div>
                <p className="text-sm text-muted-foreground">
                  {isPaid
                    ? `${formatDollars(
                        PLAN_TIERS.find((t) => t.id === planTier)?.price ?? 0,
                      )}/month`
                    : "No subscription"}
                </p>
              </div>

              {isSubscribed && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handlePortal}
                  disabled={portalLoading}
                >
                  {portalLoading ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin mr-2" />
                  ) : (
                    <CreditCard className="h-3.5 w-3.5 mr-2" />
                  )}
                  Manage Payment
                  <ExternalLink className="h-3 w-3 ml-1.5" />
                </Button>
              )}
            </div>

            {/* Budget progress */}
            <div className="space-y-2">
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">
                  Current period spend
                </span>
                <span className="font-medium font-mono">
                  {formatDollars(currentSpend)} / {formatDollars(includedBudget)}
                </span>
              </div>
              <div className="h-2.5 rounded-full bg-muted/30 overflow-hidden">
                <div
                  className={cn(
                    "h-full rounded-full transition-all",
                    budgetPercent < 75
                      ? "bg-emerald-500"
                      : budgetPercent < 90
                        ? "bg-yellow-500"
                        : "bg-red-500",
                  )}
                  style={{ width: `${Math.min(budgetPercent, 100)}%` }}
                />
              </div>
              <p
                className={cn(
                  "text-xs",
                  account.within_included
                    ? "text-emerald-600"
                    : "text-amber-600",
                )}
              >
                {account.within_included
                  ? `${(100 - budgetPercent).toFixed(1)}% of budget remaining`
                  : "Exceeding included budget"}
              </p>
            </div>
          </div>
        )}

        {/* ================================================================= */}
        {/* Available Plans                                                     */}
        {/* ================================================================= */}
        <div className="space-y-4">
          <h2 className="text-lg font-semibold">
            {isPaid ? "Change plan" : "Upgrade your plan"}
          </h2>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {PLAN_TIERS.map((tier) => {
              const isCurrent = planTier === tier.id;
              const TierIcon = tier.icon;

              return (
                <div
                  key={tier.id}
                  className={cn(
                    "relative rounded-xl border p-5 space-y-4 transition-colors",
                    isCurrent
                      ? "border-emerald-500/50 bg-emerald-500/5"
                      : "border-border hover:border-border/80",
                    tier.popular &&
                      !isCurrent &&
                      "border-primary/30 bg-primary/[0.02]",
                  )}
                >
                  {tier.popular && !isCurrent && (
                    <span className="absolute -top-2.5 left-4 px-2 py-0.5 bg-primary text-primary-foreground text-[10px] font-medium rounded-full uppercase tracking-wider">
                      Popular
                    </span>
                  )}

                  <div className="flex items-center gap-2">
                    <TierIcon className="h-4 w-4 text-muted-foreground" />
                    <h3 className="font-semibold">{tier.name}</h3>
                  </div>

                  <div className="flex items-baseline gap-1">
                    <span className="text-2xl font-bold">
                      {tier.price === 0
                        ? "Free"
                        : formatDollars(tier.price, 0)}
                    </span>
                    {tier.price > 0 && (
                      <span className="text-sm text-muted-foreground">
                        /month
                      </span>
                    )}
                  </div>

                  <ul className="space-y-1.5 text-sm text-muted-foreground">
                    {tier.features.map((feature) => (
                      <li key={feature} className="flex items-start gap-2">
                        <Check className="h-3.5 w-3.5 mt-0.5 text-emerald-500 flex-shrink-0" />
                        <span>{feature}</span>
                      </li>
                    ))}
                  </ul>

                  <div className="pt-1">
                    {isCurrent ? (
                      <Button
                        variant="outline"
                        size="sm"
                        className="w-full"
                        disabled
                      >
                        Current plan
                      </Button>
                    ) : tier.id === "free" ? (
                      isSubscribed ? (
                        <Button
                          variant="outline"
                          size="sm"
                          className="w-full"
                          onClick={handlePortal}
                          disabled={portalLoading}
                        >
                          {portalLoading ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin mr-2" />
                          ) : null}
                          Downgrade via Portal
                        </Button>
                      ) : null
                    ) : (
                      <Button
                        size="sm"
                        className="w-full"
                        onClick={() =>
                          handleCheckout(tier.id as "starter" | "pro")
                        }
                        disabled={checkoutLoading === tier.id}
                      >
                        {checkoutLoading === tier.id ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin mr-2" />
                        ) : null}
                        {isSubscribed ? "Switch to " : "Subscribe to "}
                        {tier.name}
                      </Button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* ================================================================= */}
        {/* Overage Settings (paid tiers only)                                 */}
        {/* ================================================================= */}
        {isPaid && isOrgAdmin && account && (
          <div className="rounded-xl border border-border p-6 space-y-4">
            <div>
              <h2 className="text-lg font-semibold">Overage settings</h2>
              <p className="text-sm text-muted-foreground mt-0.5">
                Control what happens when you exceed your included budget.
              </p>
            </div>

            {overageError && (
              <div className="flex items-center gap-2 px-3 py-2 rounded-md bg-destructive/5 border border-destructive/20">
                <AlertCircle className="h-3.5 w-3.5 text-destructive flex-shrink-0" />
                <span className="text-xs text-destructive">{overageError}</span>
              </div>
            )}

            {overageSuccess && (
              <div className="flex items-center gap-2 px-3 py-2 rounded-md bg-emerald-500/5 border border-emerald-500/20">
                <Check className="h-3.5 w-3.5 text-emerald-600 flex-shrink-0" />
                <span className="text-xs text-emerald-600">
                  Overage settings saved.
                </span>
              </div>
            )}

            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <p className="text-sm font-medium">
                  Enable pay-as-you-go overage
                </p>
                <p className="text-xs text-muted-foreground">
                  Continue using agents after exceeding your included budget
                </p>
              </div>
              <button
                type="button"
                role="switch"
                aria-checked={overageEnabled}
                disabled={overageSaving}
                onClick={handleOverageToggle}
                className={cn(
                  "relative inline-flex h-5 w-9 items-center rounded-full transition-colors",
                  overageEnabled ? "bg-emerald-500" : "bg-muted",
                  overageSaving && "opacity-50 cursor-not-allowed",
                )}
              >
                <span
                  className={cn(
                    "inline-block h-4 w-4 transform rounded-full bg-white transition-transform",
                    overageEnabled ? "translate-x-4.5" : "translate-x-0.5",
                  )}
                />
              </button>
            </div>

            {overageEnabled && (
              <div className="border-t border-border pt-4 space-y-3">
                <div className="space-y-1">
                  <label
                    htmlFor="overage-limit"
                    className="text-sm font-medium"
                  >
                    Maximum overage spending
                  </label>
                  <p className="text-xs text-muted-foreground">
                    Set a cap on overage charges per billing period. Leave empty
                    for no limit.
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <div className="relative w-40">
                    <span className="absolute left-3 top-1/2 -translate-y-1/2 text-sm text-muted-foreground">
                      $
                    </span>
                    <Input
                      id="overage-limit"
                      type="number"
                      min="0"
                      step="1"
                      placeholder="No limit"
                      value={overageLimit}
                      onChange={(e) => setOverageLimit(e.target.value)}
                      className="pl-7 h-9"
                    />
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleOverageLimitSave}
                    disabled={overageSaving}
                  >
                    {overageSaving ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin mr-2" />
                    ) : null}
                    Save
                  </Button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
