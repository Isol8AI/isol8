#!/usr/bin/env node
/**
 * paperclip-org-read.js
 * Nexus bootstrap + routing: read the agent roster and their health.
 *
 * Paperclip splits the org data across several endpoints:
 *   - /api/companies/:companyId/agents   — flat roster
 *   - /api/companies/:companyId/org      — hierarchical tree
 *   - /api/instance/scheduler-heartbeats — per-agent scheduler health
 *   - /api/agents/:id                    — agent detail
 *   - /api/agents/:id/runtime-state      — current execution state
 *
 * This script exposes each as a discrete mode. The routing-map builder in
 * bootstrap calls `mode: "roster_with_health"` which combines the flat
 * roster with scheduler heartbeats in one response.
 *
 * Read-only. Deterministic. Zero LLM.
 *
 * Input (stdin JSON):
 *   { mode: "agents" }
 *   { mode: "org" }
 *   { mode: "heartbeats" }
 *   { mode: "roster_with_health" }
 *   { mode: "agent",         id: "<agent-id>" }
 *   { mode: "runtime_state", id: "<agent-id>" }
 */

const { getCompanyId, pcGet, readStdin, ok, fail } = require('./paperclip-http');

async function main() {
  const input = await readStdin();
  const mode = input.mode || 'agents';
  const companyId = await getCompanyId();

  if (mode === 'agents') {
    const res = await pcGet(`/api/companies/${companyId}/agents`);
    if (!res.ok) return fail(res.reason, { status: res.status });
    const agents = Array.isArray(res.body) ? res.body : (res.body && res.body.agents) || [];
    return ok({ agents, count: agents.length });
  }

  if (mode === 'org') {
    const res = await pcGet(`/api/companies/${companyId}/org`);
    if (!res.ok) return fail(res.reason, { status: res.status });
    return ok({ org: res.body });
  }

  if (mode === 'heartbeats') {
    const res = await pcGet(`/api/instance/scheduler-heartbeats`);
    if (!res.ok) return fail(res.reason, { status: res.status });
    return ok({ heartbeats: res.body });
  }

  if (mode === 'roster_with_health') {
    const [agentsRes, hbRes] = await Promise.all([
      pcGet(`/api/companies/${companyId}/agents`),
      pcGet(`/api/instance/scheduler-heartbeats`),
    ]);
    if (!agentsRes.ok) return fail(agentsRes.reason, { status: agentsRes.status, phase: 'agents' });
    if (!hbRes.ok) return fail(hbRes.reason, { status: hbRes.status, phase: 'heartbeats' });
    const agents = Array.isArray(agentsRes.body) ? agentsRes.body : (agentsRes.body && agentsRes.body.agents) || [];
    const hbByAgent = new Map();
    const hbList = Array.isArray(hbRes.body) ? hbRes.body : (hbRes.body && hbRes.body.heartbeats) || [];
    for (const hb of hbList) {
      if (hb && hb.agentId) hbByAgent.set(hb.agentId, hb);
    }
    const merged = agents.map((a) => ({ ...a, scheduler: hbByAgent.get(a.id) || null }));
    return ok({ agents: merged, count: merged.length });
  }

  if (mode === 'agent') {
    if (!input.id) return fail('agent mode requires id');
    const res = await pcGet(`/api/agents/${encodeURIComponent(input.id)}`);
    if (!res.ok) return fail(res.reason, { status: res.status });
    return ok({ agent: res.body });
  }

  if (mode === 'runtime_state') {
    if (!input.id) return fail('runtime_state mode requires id');
    const res = await pcGet(`/api/agents/${encodeURIComponent(input.id)}/runtime-state`);
    if (!res.ok) return fail(res.reason, { status: res.status });
    return ok({ runtime_state: res.body });
  }

  return fail(`Unknown mode: ${mode}. Expected one of: agents, org, heartbeats, roster_with_health, agent, runtime_state`);
}

main().catch((err) => fail(err.message || String(err)));
