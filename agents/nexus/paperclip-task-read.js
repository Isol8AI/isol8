#!/usr/bin/env node
/**
 * paperclip-task-read.js
 * Nexus requirements 7, 9, 12: cross-agent synthesis data source.
 *
 * Wraps Paperclip's issue read endpoints. Read-only. Covers the access
 * patterns Nexus needs for the heartbeat sweep, synthesis reports, and
 * circuit breaker.
 *
 * Deterministic. Zero LLM.
 *
 * Input (stdin JSON):
 *   { mode: "list",           query?: { status?, assigneeAgentId?, projectId?, limit? } }
 *   { mode: "by_id",          id: "<issue-id-or-key>" }
 *   { mode: "by_agent",       assignee_agent_id: "<id>", query?: { ... } }
 *   { mode: "heartbeat_ctx",  id: "<issue-id>" }    // summary with comments+ancestors
 *
 * Output:
 *   list / by_agent:     {ok: true, issues: [...]}
 *   by_id / heartbeat:   {ok: true, issue: {...}}
 */

const { getCompanyId, pcGet, readStdin, ok, fail } = require('./paperclip-http');

async function main() {
  const input = await readStdin();
  const mode = input.mode || 'list';
  const companyId = await getCompanyId();

  if (mode === 'list' || mode === 'by_agent') {
    const query = { ...(input.query || {}) };
    if (mode === 'by_agent') {
      if (!input.assignee_agent_id) return fail('by_agent mode requires assignee_agent_id');
      query.assigneeAgentId = input.assignee_agent_id;
    }
    const res = await pcGet(`/api/companies/${companyId}/issues`, query);
    if (!res.ok) return fail(res.reason, { status: res.status });
    const issues = Array.isArray(res.body) ? res.body : (res.body && res.body.issues) || [];
    return ok({ issues, count: issues.length });
  }

  if (mode === 'by_id') {
    if (!input.id) return fail('by_id mode requires id');
    const res = await pcGet(`/api/issues/${encodeURIComponent(input.id)}`);
    if (!res.ok) return fail(res.reason, { status: res.status });
    return ok({ issue: res.body });
  }

  if (mode === 'heartbeat_ctx') {
    if (!input.id) return fail('heartbeat_ctx mode requires id');
    const res = await pcGet(`/api/issues/${encodeURIComponent(input.id)}/heartbeat-context`);
    if (!res.ok) return fail(res.reason, { status: res.status });
    return ok({ issue: res.body });
  }

  return fail(`Unknown mode: ${mode}. Expected one of: list, by_id, by_agent, heartbeat_ctx`);
}

main().catch((err) => fail(err.message || String(err)));
