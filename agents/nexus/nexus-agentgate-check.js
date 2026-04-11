#!/usr/bin/env node
/**
 * nexus-agentgate-check.js
 * Nexus requirements 6, 19: surface approval requests on newly-created issues.
 *
 * Paperclip's governance model is approval-based, not gate-based — there's
 * no per-agent gate config to pre-check. Approvals are created server-side
 * based on the issue's executionPolicy, the agent's permissions, and issue
 * classification. This script runs AFTER paperclip-task-create.js returns a
 * new issue and looks up whether any approval was auto-generated.
 *
 * Deterministic. Zero LLM.
 *
 * Input (stdin JSON):
 *   { issue_id: string }   // required — the newly-created issue ID or key
 *
 * Output:
 *   {ok: true, gate: false, issue_id}
 *   {ok: true, gate: true, issue_id, approvals: [...], count, primary: {id, type, status}}
 */

const { pcGet, readStdin, ok, fail } = require('./paperclip-http');

async function main() {
  const input = await readStdin();
  if (!input.issue_id) return fail('Missing required field: issue_id');

  const res = await pcGet(`/api/issues/${encodeURIComponent(input.issue_id)}/approvals`);
  if (!res.ok) return fail(res.reason, { status: res.status });

  const approvals = Array.isArray(res.body) ? res.body : (res.body && res.body.approvals) || [];
  const pending = approvals.filter((a) => {
    const status = (a.status || '').toLowerCase();
    return status === 'pending' || status === 'revision_requested' || status === '';
  });

  if (pending.length === 0) {
    return ok({ gate: false, issue_id: input.issue_id });
  }

  const primary = pending[0];
  return ok({
    gate: true,
    issue_id: input.issue_id,
    approvals: pending,
    count: pending.length,
    primary: {
      id: primary.id,
      type: primary.type || null,
      status: primary.status || 'pending',
      requested_by_agent_id: primary.requestedByAgentId || primary.requested_by_agent_id || null,
    },
  });
}

main().catch((err) => fail(err.message || String(err)));
