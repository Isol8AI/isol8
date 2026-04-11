#!/usr/bin/env node
/**
 * paperclip-budget-read.js
 * Nexus requirements 5, 11: budget pre-flight + ceiling alerts.
 *
 * Paperclip does not expose a single "get remaining budget for agent" endpoint.
 * Instead, budget state is derived by combining:
 *   - agents.budgetMonthlyCents  (the allocation, stored on the agent record)
 *   - costs/by-agent             (the consumed spend in the current window)
 *   - budgets/overview           (company-level rollup)
 *   - costs/window-spend         (quota-window-scoped spend)
 *
 * This script exposes those as discrete modes and does not attempt the
 * remaining-balance computation itself — nexus-budget-check.js handles that
 * so the arithmetic stays in one place.
 *
 * Deterministic. Zero LLM.
 *
 * Input (stdin JSON):
 *   { mode: "by_agent",  from?: "YYYY-MM-DD", to?: "YYYY-MM-DD" }
 *   { mode: "overview" }
 *   { mode: "window_spend" }
 *   { mode: "quota_windows" }
 *   { mode: "agent_allocation", agent_id: "<id>" }   // reads budgetMonthlyCents
 */

const { getCompanyId, pcGet, readStdin, ok, fail } = require('./paperclip-http');

async function main() {
  const input = await readStdin();
  const mode = input.mode || 'by_agent';
  const companyId = await getCompanyId();

  if (mode === 'by_agent') {
    const query = {};
    if (input.from) query.from = input.from;
    if (input.to) query.to = input.to;
    const res = await pcGet(`/api/companies/${companyId}/costs/by-agent`, query);
    if (!res.ok) return fail(res.reason, { status: res.status });
    return ok({ by_agent: res.body });
  }

  if (mode === 'overview') {
    const res = await pcGet(`/api/companies/${companyId}/budgets/overview`);
    if (!res.ok) return fail(res.reason, { status: res.status });
    return ok({ overview: res.body });
  }

  if (mode === 'window_spend') {
    const res = await pcGet(`/api/companies/${companyId}/costs/window-spend`);
    if (!res.ok) return fail(res.reason, { status: res.status });
    return ok({ window_spend: res.body });
  }

  if (mode === 'quota_windows') {
    const res = await pcGet(`/api/companies/${companyId}/costs/quota-windows`);
    if (!res.ok) return fail(res.reason, { status: res.status });
    return ok({ quota_windows: res.body });
  }

  if (mode === 'agent_allocation') {
    if (!input.agent_id) return fail('agent_allocation mode requires agent_id');
    const res = await pcGet(`/api/agents/${encodeURIComponent(input.agent_id)}`);
    if (!res.ok) return fail(res.reason, { status: res.status });
    const agent = res.body || {};
    return ok({
      agent_id: input.agent_id,
      budget_monthly_cents: agent.budgetMonthlyCents ?? null,
      agent,
    });
  }

  return fail(`Unknown mode: ${mode}. Expected one of: by_agent, overview, window_spend, quota_windows, agent_allocation`);
}

main().catch((err) => fail(err.message || String(err)));
