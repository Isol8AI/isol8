"use client";

import { useState, useMemo, useEffect, useCallback } from "react";
import { Loader2, RefreshCw, AlertCircle } from "lucide-react";
import { useGatewayRpc } from "@/hooks/useGatewayRpc";
import { useApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

// =============================================================================
// Types
// =============================================================================

const MARKUP = 1.4;

// Bedrock pricing per token ($ per token, NOT per 1M tokens)
const MODEL_PRICING: Record<string, { input: number; output: number }> = {
  // Claude Opus 4.6 / 4.5: $5/$25 per 1M tokens
  "us.anthropic.claude-opus-4-6-v1": { input: 5 / 1e6, output: 25 / 1e6 },
  "us.anthropic.claude-opus-4-5-20251101-v1:0": { input: 5 / 1e6, output: 25 / 1e6 },
  // Claude Sonnet 4.5: $3/$15 per 1M tokens
  "us.anthropic.claude-sonnet-4-5-20250929-v1:0": { input: 3 / 1e6, output: 15 / 1e6 },
  // Claude Haiku 4.5: $1/$5 per 1M tokens
  "us.anthropic.claude-haiku-4-5-20251001-v1:0": { input: 1 / 1e6, output: 5 / 1e6 },
};

// Fallback: assume Sonnet pricing if model unknown
const FALLBACK_PRICING = { input: 3 / 1e6, output: 15 / 1e6 };

function getModelPricing(model: string): { input: number; output: number } {
  // Try exact match first
  if (MODEL_PRICING[model]) return MODEL_PRICING[model];
  // Try stripping "amazon-bedrock/" prefix
  const stripped = model.replace(/^amazon-bedrock\//, "");
  if (MODEL_PRICING[stripped]) return MODEL_PRICING[stripped];
  // Match by substring
  for (const [key, pricing] of Object.entries(MODEL_PRICING)) {
    if (model.includes(key) || key.includes(model)) return pricing;
  }
  // Guess by name
  const lower = model.toLowerCase();
  if (lower.includes("opus")) return { input: 5 / 1e6, output: 25 / 1e6 };
  if (lower.includes("haiku")) return { input: 1 / 1e6, output: 5 / 1e6 };
  return FALLBACK_PRICING;
}

// REST API types
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

interface ModelUsage {
  model: string;
  cost: number;
  requests: number;
}

interface UsageResponse {
  period: UsagePeriod;
  total_cost: number;
  total_requests: number;
  by_model: ModelUsage[];
  by_day: { date: string; cost: number }[];
}

// Gateway sessions.list types
interface GatewaySession {
  key: string;
  agentId?: string;
  model?: string;
  label?: string;
  displayName?: string;
  inputTokens?: number;
  outputTokens?: number;
  totalTokens?: number;
  updatedAt?: number | null;
  [key: string]: unknown;
}

interface SessionsListResponse {
  sessions?: GatewaySession[];
  count?: number;
  [key: string]: unknown;
}

// =============================================================================
// Helpers
// =============================================================================

const TOOL_MODEL_IDS = ["perplexity_search", "elevenlabs_tts", "openai_tts", "firecrawl_scrape"];

const TOOL_DISPLAY_NAMES: Record<string, string> = {
  perplexity_search: "Web Search",
  elevenlabs_tts: "Text-to-Speech",
  openai_tts: "Text-to-Speech (OpenAI)",
  firecrawl_scrape: "Web Scrape",
};

function isToolUsage(modelId: string): boolean {
  return TOOL_MODEL_IDS.some((t) => modelId.includes(t));
}

function toolDisplayName(modelId: string): string {
  for (const [key, name] of Object.entries(TOOL_DISPLAY_NAMES)) {
    if (modelId.includes(key)) return name;
  }
  return modelId;
}

function shortModelName(model: string): string {
  // Strip provider prefix
  const stripped = model.replace(/^amazon-bedrock\//, "");
  const parts = stripped.split(".");
  const last = parts[parts.length - 1] || stripped;
  return last.replace(/-\d{8}.*$/, "").replace(/:.*$/, "");
}

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
  const { get } = useApi();

  // --- REST API data (billing pipeline — may be empty if pipeline broken) ---
  const [account, setAccount] = useState<BillingAccount | null>(null);
  const [usage, setUsage] = useState<UsageResponse | null>(null);
  const [billingLoading, setBillingLoading] = useState(true);
  const [billingError, setBillingError] = useState<string | null>(null);

  const fetchBilling = useCallback(async () => {
    setBillingLoading(true);
    setBillingError(null);
    try {
      const [acct, usg] = await Promise.all([
        get("/billing/account") as Promise<BillingAccount>,
        get("/billing/usage") as Promise<UsageResponse>,
      ]);
      setAccount(acct);
      setUsage(usg);
    } catch (err) {
      setBillingError(err instanceof Error ? err.message : "Failed to fetch billing data");
    } finally {
      setBillingLoading(false);
    }
  }, [get]);

  useEffect(() => {
    fetchBilling();
  }, [fetchBilling]);

  // --- Gateway session data (real token counts from OpenClaw) ---
  const {
    data: sessionsData,
    error: sessionsError,
    isLoading: sessionsLoading,
    mutate: mutateSessions,
  } = useGatewayRpc<SessionsListResponse>("sessions.list");

  // Aggregate session token data + compute estimated costs
  const sessionStats = useMemo(() => {
    const sessions = sessionsData?.sessions ?? [];
    let totalInput = 0;
    let totalOutput = 0;
    let totalTokens = 0;
    let estimatedRawCost = 0;

    const byModel: Record<string, { input: number; output: number; total: number; cost: number; sessions: number }> = {};
    const byAgent: Record<string, { input: number; output: number; total: number; cost: number; sessions: number }> = {};

    for (const s of sessions) {
      const inp = s.inputTokens ?? 0;
      const out = s.outputTokens ?? 0;
      const tot = s.totalTokens ?? (inp + out);
      const pricing = getModelPricing(s.model || "");
      const cost = inp * pricing.input + out * pricing.output;

      totalInput += inp;
      totalOutput += out;
      totalTokens += tot;
      estimatedRawCost += cost;

      // By model
      const modelKey = s.model || "unknown";
      if (!byModel[modelKey]) {
        byModel[modelKey] = { input: 0, output: 0, total: 0, cost: 0, sessions: 0 };
      }
      byModel[modelKey].input += inp;
      byModel[modelKey].output += out;
      byModel[modelKey].total += tot;
      byModel[modelKey].cost += cost;
      byModel[modelKey].sessions += 1;

      // By agent
      const agentKey = s.agentId || s.displayName || s.label || s.key;
      if (!byAgent[agentKey]) {
        byAgent[agentKey] = { input: 0, output: 0, total: 0, cost: 0, sessions: 0 };
      }
      byAgent[agentKey].input += inp;
      byAgent[agentKey].output += out;
      byAgent[agentKey].total += tot;
      byAgent[agentKey].cost += cost;
      byAgent[agentKey].sessions += 1;
    }

    const estimatedBillable = estimatedRawCost * MARKUP;
    const estimatedRevenue = estimatedBillable - estimatedRawCost;

    return {
      totalInput,
      totalOutput,
      totalTokens,
      estimatedRawCost,
      estimatedBillable,
      estimatedRevenue,
      sessionCount: sessions.length,
      byModel: Object.entries(byModel).sort(([, a], [, b]) => b.cost - a.cost),
      byAgent: Object.entries(byAgent).sort(([, a], [, b]) => b.total - a.total),
    };
  }, [sessionsData]);

  // --- Categorize REST API by_model into LLM vs Tool ---
  const { llmModels, toolModels, totalToolCost } = useMemo(() => {
    const models = usage?.by_model ?? [];
    const llm: ModelUsage[] = [];
    const tools: ModelUsage[] = [];
    let toolCost = 0;
    for (const entry of models) {
      if (isToolUsage(entry.model)) {
        tools.push(entry);
        toolCost += entry.cost;
      } else {
        llm.push(entry);
      }
    }
    return {
      llmModels: llm.sort((a, b) => b.cost - a.cost),
      toolModels: tools.sort((a, b) => b.cost - a.cost),
      totalToolCost: toolCost,
    };
  }, [usage]);

  // --- Derived values ---
  const period = account?.current_period;

  // Always use gateway-estimated costs (computed from live session tokens with
  // accurate Bedrock pricing). The billing API lags behind (poller runs every
  // 5 min) and uses DB pricing which may not have every model ID, so gateway
  // estimates are more responsive and accurate for display.
  const effectiveCost = sessionStats.estimatedBillable;
  const effectiveRawCost = sessionStats.estimatedRawCost;
  const effectiveRevenue = effectiveCost - effectiveRawCost;
  const budgetTotal = period?.included_budget ?? 0;
  const budgetPercent = budgetTotal > 0 ? (effectiveCost / budgetTotal) * 100 : 0;

  const handleRefresh = useCallback(() => {
    fetchBilling();
    mutateSessions();
  }, [fetchBilling, mutateSessions]);

  // --- Loading state ---
  if (billingLoading && sessionsLoading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Usage & Billing</h2>
        <Button variant="ghost" size="sm" onClick={handleRefresh}>
          <RefreshCw className="h-3.5 w-3.5" />
        </Button>
      </div>

      {billingError && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-md bg-destructive/5 border border-destructive/20">
          <AlertCircle className="h-3.5 w-3.5 text-destructive flex-shrink-0" />
          <span className="text-xs text-destructive">{billingError}</span>
          <Button variant="outline" size="sm" className="ml-auto h-6 text-xs" onClick={fetchBilling}>
            Retry
          </Button>
        </div>
      )}

      {/* Plan + Period */}
      {account && period && (
        <>
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            <span>
              Plan: <span className="font-medium text-foreground">{account.plan_tier}</span>
            </span>
            <span>
              Period: <span className="font-medium text-foreground">{period.start} — {period.end}</span>
            </span>
            {account.has_subscription && (
              <span className="text-emerald-600 font-medium">Active</span>
            )}
          </div>

          {/* Budget bar */}
          <div className="rounded-lg border border-border p-4 space-y-2">
            <div className="flex items-center justify-between text-sm">
              <span className="font-medium">Budget</span>
              <span className="text-muted-foreground">
                {formatDollars(effectiveCost)} / {formatDollars(budgetTotal)}
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
            {effectiveCost > 0 && (
              <p className="text-xs text-muted-foreground/60">
                Based on gateway session token usage
              </p>
            )}
          </div>
        </>
      )}

      {/* Cost Breakdown */}
      <div className="rounded-lg border border-border p-4 space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium">Cost Breakdown</h3>
        </div>
        <div className="space-y-1.5">
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">LLM Cost (raw)</span>
            <span className="font-mono">{formatDollars(effectiveRawCost, 4)}</span>
          </div>
          {totalToolCost > 0 && (
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Tool Usage</span>
              <span className="font-mono">{formatDollars(totalToolCost, 4)}</span>
            </div>
          )}
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Platform Fee (40%)</span>
            <span className="font-mono">{formatDollars(effectiveRevenue, 4)}</span>
          </div>
          <div className="border-t border-border my-1" />
          <div className="flex items-center justify-between text-sm font-medium">
            <span>Total Billable</span>
            <span className="font-mono">{formatDollars(effectiveCost, 4)}</span>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-emerald-600">Your Revenue</span>
            <span className="font-mono text-emerald-600">{formatDollars(effectiveRevenue, 4)}</span>
          </div>
        </div>
        <div className="text-xs text-muted-foreground/60 pt-1">
          {sessionStats.sessionCount} sessions · {formatTokens(sessionStats.totalTokens)} tokens
        </div>
      </div>

      {/* Token Breakdown */}
      <div className="rounded-lg border border-border p-4 space-y-3">
        <h3 className="text-sm font-medium">Token Usage</h3>

        {sessionsLoading && (
          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
        )}

        {sessionsError && (
          <p className="text-xs text-destructive">{sessionsError.message}</p>
        )}

        {!sessionsLoading && !sessionsError && (
          <>
            <div className="grid grid-cols-3 gap-3">
              <div>
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground/60">Input</div>
                <div className="text-lg font-semibold">{formatTokens(sessionStats.totalInput)}</div>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground/60">Output</div>
                <div className="text-lg font-semibold">{formatTokens(sessionStats.totalOutput)}</div>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground/60">Total</div>
                <div className="text-lg font-semibold">{formatTokens(sessionStats.totalTokens)}</div>
              </div>
            </div>

            {sessionStats.byAgent.length > 0 && (
              <div className="space-y-1">
                <div className="text-xs text-muted-foreground font-medium">By Agent</div>
                {sessionStats.byAgent.map(([agent, stats]) => (
                  <div
                    key={agent}
                    className="flex items-center justify-between px-2 py-1.5 rounded-md hover:bg-accent/50 text-xs"
                  >
                    <span className="truncate">{agent}</span>
                    <span className="text-muted-foreground flex-shrink-0 ml-2">
                      {formatTokens(stats.total)} tokens · {formatDollars(stats.cost, 4)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>

      {/* By Model table */}
      {sessionStats.byModel.length > 0 && (
        <div className="rounded-lg border border-border overflow-hidden">
          <div className="px-4 py-2 bg-muted/20 border-b border-border">
            <h3 className="text-sm font-medium">By Model</h3>
          </div>
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border text-muted-foreground">
                <th className="text-left px-4 py-2 font-medium">Model</th>
                <th className="text-right px-4 py-2 font-medium">Sessions</th>
                <th className="text-right px-4 py-2 font-medium">Tokens</th>
                <th className="text-right px-4 py-2 font-medium">Raw Cost</th>
                <th className="text-right px-4 py-2 font-medium">Billable</th>
              </tr>
            </thead>
            <tbody>
              {sessionStats.byModel.map(([model, stats]) => (
                <tr key={model} className="border-b border-border/50 hover:bg-accent/30">
                  <td className="px-4 py-2 font-mono truncate max-w-[180px]" title={model}>
                    {shortModelName(model)}
                  </td>
                  <td className="px-4 py-2 text-right text-muted-foreground">
                    {stats.sessions}
                  </td>
                  <td className="px-4 py-2 text-right text-muted-foreground">
                    {formatTokens(stats.total)}
                  </td>
                  <td className="px-4 py-2 text-right font-mono text-muted-foreground">
                    {formatDollars(stats.cost, 4)}
                  </td>
                  <td className="px-4 py-2 text-right font-mono">
                    {formatDollars(stats.cost * MARKUP, 4)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Tool Usage table (from REST API) */}
      {toolModels.length > 0 && (
        <div className="rounded-lg border border-border overflow-hidden">
          <div className="px-4 py-2 bg-muted/20 border-b border-border">
            <h3 className="text-sm font-medium">Tool Usage</h3>
          </div>
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border text-muted-foreground">
                <th className="text-left px-4 py-2 font-medium">Tool</th>
                <th className="text-right px-4 py-2 font-medium">Requests</th>
                <th className="text-right px-4 py-2 font-medium">Cost</th>
              </tr>
            </thead>
            <tbody>
              {toolModels.map((entry) => (
                <tr key={entry.model} className="border-b border-border/50 hover:bg-accent/30">
                  <td className="px-4 py-2">{toolDisplayName(entry.model)}</td>
                  <td className="px-4 py-2 text-right text-muted-foreground">
                    {entry.requests}
                  </td>
                  <td className="px-4 py-2 text-right font-mono">
                    {entry.cost === 0 ? (
                      <span className="text-muted-foreground/60">$0.00 (BYOK)</span>
                    ) : (
                      formatDollars(entry.cost, 4)
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Raw data */}
      <details className="group">
        <summary className="text-xs text-muted-foreground/60 cursor-pointer hover:text-muted-foreground">
          Raw data
        </summary>
        <pre className="mt-2 text-xs bg-muted/30 rounded-lg p-3 overflow-auto max-h-48">
          {JSON.stringify({ account, usage, sessionsData }, null, 2)}
        </pre>
      </details>
    </div>
  );
}
