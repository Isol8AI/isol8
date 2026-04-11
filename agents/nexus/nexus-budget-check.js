#!/usr/bin/env node
/**
 * nexus-budget-check.js
 * Nexus requirement 5: pre-flight budget validation before issue creation.
 *
 * Paperclip has no single "remaining for agent" endpoint, so this script
 * combines:
 *   - GET /api/agents/:id             → budgetMonthlyCents (the allocation)
 *   - GET /api/companies/:id/costs/by-agent → consumed_cents in the current window
 *
 * Remaining = allocation − consumed. If estimated_cost_cents would exceed
 * remaining, returns {block: true} with template data so the caller can
 * fire the budget alert notification instead of creating the issue.
 *
 * The script also identifies underutilized peers (utilization < 40%) as
 * reallocation candidates — surfaced in `alternatives[]` for the template.
 *
 * Deterministic. Zero LLM.
 *
 * Input (stdin JSON):
 *   {
 *     target_agent_id: string,              // required
 *     estimated_cost_cents: number,         // required
 *     ceiling_percent?: number              // default 80 — soft warning threshold
 *   }
 *
 * Output:
 *   {ok: true, block: false, remaining_cents, budget_cents, utilization_percent, warning?: true}
 *   {ok: true, block: true, reason, remaining_cents, budget_cents, alternatives: [...]}
 */

const { pcGet, getCompanyId, readStdin, ok, fail } = require('./paperclip-http');

function extractConsumedCents(byAgent, agentId) {
  if (!byAgent) return 0;
  const rows = Array.isArray(byAgent) ? byAgent : (byAgent.rows || byAgent.byAgent || []);
  for (const row of rows) {
    const id = row.agentId || row.agent_id || row.id;
    if (id === agentId) {
      return row.consumedCents ?? row.consumed_cents ?? row.totalCents ?? row.total_cents ?? 0;
    }
  }
  return 0;
}

function utilizationBuckets(byAgent) {
  const rows = Array.isArray(byAgent) ? byAgent : (byAgent && (byAgent.rows || byAgent.byAgent)) || [];
  return rows.map((r) => ({
    agent_id: r.agentId || r.agent_id || r.id,
    consumed_cents: r.consumedCents ?? r.consumed_cents ?? r.totalCents ?? 0,
    budget_cents: r.budgetMonthlyCents ?? r.budget_monthly_cents ?? null,
  }));
}

async function main() {
  const input = await readStdin();
  if (!input.target_agent_id) return fail('Missing required field: target_agent_id');
  if (typeof input.estimated_cost_cents !== 'number') {
    return fail('Missing or invalid required field: estimated_cost_cents (number)');
  }
  const ceilingPercent = input.ceiling_percent ?? 80;

  const companyId = await getCompanyId();

  const [agentRes, costsRes] = await Promise.all([
    pcGet(`/api/agents/${encodeURIComponent(input.target_agent_id)}`),
    pcGet(`/api/companies/${companyId}/costs/by-agent`),
  ]);
  if (!agentRes.ok) return fail(`agent fetch failed: ${agentRes.reason}`, { status: agentRes.status });
  if (!costsRes.ok) return fail(`costs/by-agent fetch failed: ${costsRes.reason}`, { status: costsRes.status });

  const agent = agentRes.body || {};
  const budgetCents = agent.budgetMonthlyCents ?? null;
  if (budgetCents == null) {
    return ok({
      block: false,
      warning: true,
      reason: 'Agent has no budgetMonthlyCents set — cannot enforce ceiling',
      remaining_cents: null,
      budget_cents: null,
      utilization_percent: null,
    });
  }

  const consumed = extractConsumedCents(costsRes.body, input.target_agent_id);
  const remaining = budgetCents - consumed;
  const projected = consumed + input.estimated_cost_cents;
  const utilization = budgetCents > 0 ? (projected / budgetCents) * 100 : 100;

  if (projected > budgetCents) {
    // Find underutilized peers for reallocation suggestions
    const buckets = utilizationBuckets(costsRes.body);
    const alternatives = buckets
      .filter((b) => b.agent_id && b.agent_id !== input.target_agent_id && b.budget_cents)
      .map((b) => ({
        agent_id: b.agent_id,
        utilization_percent: b.budget_cents > 0 ? (b.consumed_cents / b.budget_cents) * 100 : 0,
        remaining_cents: b.budget_cents - b.consumed_cents,
      }))
      .filter((b) => b.utilization_percent < 40)
      .sort((a, b) => b.remaining_cents - a.remaining_cents)
      .slice(0, 3);

    return ok({
      block: true,
      reason: `Task estimated at ${input.estimated_cost_cents}¢ would exceed remaining ${remaining}¢ on agent ${input.target_agent_id}`,
      remaining_cents: remaining,
      budget_cents: budgetCents,
      consumed_cents: consumed,
      estimated_cost_cents: input.estimated_cost_cents,
      alternatives,
    });
  }

  return ok({
    block: false,
    warning: utilization >= ceilingPercent,
    remaining_cents: remaining,
    budget_cents: budgetCents,
    consumed_cents: consumed,
    utilization_percent: Math.round(utilization * 10) / 10,
  });
}

main().catch((err) => fail(err.message || String(err)));
