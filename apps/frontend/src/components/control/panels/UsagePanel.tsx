"use client";

import { useState, useEffect, useCallback } from "react";
import { Loader2, RefreshCw, AlertCircle } from "lucide-react";
import { useOrganization } from "@clerk/nextjs";
import { useBilling } from "@/hooks/useBilling";
import type { UsageSummary } from "@/hooks/useBilling";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

// =============================================================================
// Helpers
// =============================================================================

function formatDollars(amount: number, decimals = 2): string {
  return `$${amount.toFixed(decimals)}`;
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString();
}

// =============================================================================
// Component
// =============================================================================

export function UsagePanel() {
  const { account, isLoading: accountLoading, fetchUsage, toggleOverage, refresh } = useBilling();
  const { membership } = useOrganization();
  const isOrgAdmin = !membership || membership.role === "org:admin";

  // Usage data
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [usageLoading, setUsageLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Overage controls
  const [overageEnabled, setOverageEnabled] = useState(false);
  const [overageLimit, setOverageLimit] = useState<string>("");
  const [overageSaving, setOverageSaving] = useState(false);

  const loadUsage = useCallback(async () => {
    setUsageLoading(true);
    setError(null);
    try {
      const data = await fetchUsage();
      setUsage(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch usage data");
    } finally {
      setUsageLoading(false);
    }
  }, [fetchUsage]);

  useEffect(() => {
    loadUsage();
  }, [loadUsage]);

  // Sync overage state from account
  useEffect(() => {
    if (account) {
      setOverageEnabled(account.overage_enabled);
      setOverageLimit(account.overage_limit != null ? String(account.overage_limit) : "");
    }
  }, [account]);

  const handleRefresh = useCallback(() => {
    refresh();
    loadUsage();
  }, [refresh, loadUsage]);

  const handleOverageToggle = useCallback(async () => {
    const newEnabled = !overageEnabled;
    setOverageSaving(true);
    try {
      const limit = overageLimit ? parseFloat(overageLimit) : null;
      await toggleOverage(newEnabled, limit);
      setOverageEnabled(newEnabled);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update overage");
    } finally {
      setOverageSaving(false);
    }
  }, [overageEnabled, overageLimit, toggleOverage]);

  const handleOverageLimitSave = useCallback(async () => {
    setOverageSaving(true);
    try {
      const limit = overageLimit ? parseFloat(overageLimit) : null;
      await toggleOverage(overageEnabled, limit);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update overage limit");
    } finally {
      setOverageSaving(false);
    }
  }, [overageEnabled, overageLimit, toggleOverage]);

  // --- Loading state ---
  if (accountLoading && usageLoading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const currentSpend = account?.current_spend ?? 0;
  const includedBudget = account?.included_budget ?? 0;
  const budgetPercent = includedBudget > 0 ? (currentSpend / includedBudget) * 100 : 0;
  const isPaid = account?.tier === "starter" || account?.tier === "pro";

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Usage & Billing</h2>
        <Button variant="ghost" size="sm" onClick={handleRefresh}>
          <RefreshCw className="h-3.5 w-3.5" />
        </Button>
      </div>

      {error && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-md bg-destructive/5 border border-destructive/20">
          <AlertCircle className="h-3.5 w-3.5 text-destructive flex-shrink-0" />
          <span className="text-xs text-destructive">{error}</span>
          <Button variant="outline" size="sm" className="ml-auto h-6 text-xs" onClick={handleRefresh}>
            Retry
          </Button>
        </div>
      )}

      {/* Plan + Status */}
      {account && (
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          <span>
            Plan: <span className="font-medium text-foreground capitalize">{account.tier}</span>
          </span>
          {account.is_subscribed && (
            <span className="text-emerald-600 font-medium">Active Subscription</span>
          )}
          {usage?.period && (
            <span>
              Period: <span className="font-medium text-foreground">{usage.period}</span>
            </span>
          )}
        </div>
      )}

      {/* Budget bar */}
      {account && (
        <div className="rounded-lg border border-border p-4 space-y-2">
          <div className="flex items-center justify-between text-sm">
            <span className="font-medium">Budget</span>
            <span className="text-muted-foreground">
              {formatDollars(currentSpend)} / {formatDollars(includedBudget)}
              <span className="ml-2 text-xs">({budgetPercent.toFixed(1)}%)</span>
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
          {account.within_included ? (
            <p className="text-xs text-emerald-600">Within included budget</p>
          ) : (
            <p className="text-xs text-amber-600">Exceeding included budget</p>
          )}
        </div>
      )}

      {/* Token Breakdown */}
      {usage && (
        <div className="rounded-lg border border-border p-4 space-y-3">
          <h3 className="text-sm font-medium">Token Usage</h3>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground/60">Input</div>
              <div className="text-lg font-semibold">{formatTokens(usage.total_input_tokens)}</div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground/60">Output</div>
              <div className="text-lg font-semibold">{formatTokens(usage.total_output_tokens)}</div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground/60">Cache Read</div>
              <div className="text-lg font-semibold">{formatTokens(usage.total_cache_read_tokens)}</div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground/60">Cache Write</div>
              <div className="text-lg font-semibold">{formatTokens(usage.total_cache_write_tokens)}</div>
            </div>
          </div>
          <div className="border-t border-border pt-2 flex items-center justify-between text-xs text-muted-foreground">
            <span>{usage.request_count} requests this period</span>
            <span>Total spend: {formatDollars(usage.total_spend, 4)}</span>
          </div>
        </div>
      )}

      {/* Overage Settings (paid tiers only) */}
      {isPaid && account && (
        <div className="rounded-lg border border-border p-4 space-y-3">
          <h3 className="text-sm font-medium">Overage Settings</h3>
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <p className="text-sm">Allow overage spending</p>
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
            <div className="flex items-center gap-2 pt-1">
              <label className="text-xs text-muted-foreground whitespace-nowrap">
                Spending limit ($):
              </label>
              <Input
                type="number"
                min="0"
                step="1"
                placeholder="No limit"
                value={overageLimit}
                onChange={(e) => setOverageLimit(e.target.value)}
                className="h-7 w-28 text-xs"
              />
              <Button
                variant="outline"
                size="sm"
                className="h-7 text-xs"
                onClick={handleOverageLimitSave}
                disabled={overageSaving}
              >
                {overageSaving ? <Loader2 className="h-3 w-3 animate-spin" /> : "Save"}
              </Button>
            </div>
          )}
        </div>
      )}

      {/* Per-member table (org admins only) */}
      {isOrgAdmin && usage && usage.by_member && usage.by_member.length > 0 && (
        <div className="rounded-lg border border-border overflow-hidden">
          <div className="px-4 py-2 bg-muted/20 border-b border-border">
            <h3 className="text-sm font-medium">Usage by Member</h3>
          </div>
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border text-muted-foreground">
                <th className="text-left px-4 py-2 font-medium">Member</th>
                <th className="text-right px-4 py-2 font-medium">Requests</th>
                <th className="text-right px-4 py-2 font-medium">Spend</th>
              </tr>
            </thead>
            <tbody>
              {usage.by_member.map((member) => (
                <tr key={member.user_id} className="border-b border-border/50 hover:bg-accent/30">
                  <td className="px-4 py-2">
                    <div>{member.display_name || member.email || member.user_id}</div>
                    {member.display_name && member.email && (
                      <div className="text-muted-foreground/60">{member.email}</div>
                    )}
                  </td>
                  <td className="px-4 py-2 text-right text-muted-foreground">
                    {member.request_count}
                  </td>
                  <td className="px-4 py-2 text-right font-mono">
                    {formatDollars(member.total_spend, 4)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Lifetime spend */}
      {(usage || account) && (
        <div className="rounded-lg border border-border p-4">
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Lifetime Spend</span>
            <span className="font-mono font-medium">
              {formatDollars(usage?.lifetime_spend ?? account?.lifetime_spend ?? 0)}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
