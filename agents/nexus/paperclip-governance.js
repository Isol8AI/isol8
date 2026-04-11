#!/usr/bin/env node
/**
 * paperclip-governance.js
 * Nexus requirement 6, 19: surface approval requests to the user.
 *
 * Paperclip's governance model is approval-based, not gate-based. There is
 * no per-agent "gate config" that Nexus can pre-check before creating an
 * issue. Instead:
 *   - Each issue is created with an executionPolicy (set by paperclip-task-create)
 *   - Paperclip's server may create an Approval record for the issue based on
 *     that policy, the agent's configured permissions, and issue classification
 *   - Nexus polls /api/companies/:companyId/approvals?status=pending each
 *     heartbeat to surface anything awaiting user action
 *   - Nexus can also look up approvals for a specific issue after create
 *
 * This means nexus-agentgate-check.js is a POST-creation check, not a pre-flight
 * one. The delegation flow is: create → check approvals on the new issue →
 * if any pending, surface to user; if not, proceed.
 *
 * Read-only. Deterministic. Zero LLM.
 *
 * Input (stdin JSON):
 *   { mode: "pending",  status?: "pending" | "approved" | "rejected" | "revision_requested" }
 *   { mode: "by_issue", issue_id: "<id-or-key>" }
 *   { mode: "detail",   approval_id: "<id>" }
 */

const { getCompanyId, pcGet, readStdin, ok, fail } = require('./paperclip-http');

async function main() {
  const input = await readStdin();
  const mode = input.mode || 'pending';
  const companyId = await getCompanyId();

  if (mode === 'pending') {
    const query = { status: input.status || 'pending' };
    const res = await pcGet(`/api/companies/${companyId}/approvals`, query);
    if (!res.ok) return fail(res.reason, { status: res.status });
    const approvals = Array.isArray(res.body) ? res.body : (res.body && res.body.approvals) || [];
    return ok({ approvals, count: approvals.length });
  }

  if (mode === 'by_issue') {
    if (!input.issue_id) return fail('by_issue mode requires issue_id');
    const res = await pcGet(`/api/issues/${encodeURIComponent(input.issue_id)}/approvals`);
    if (!res.ok) return fail(res.reason, { status: res.status });
    const approvals = Array.isArray(res.body) ? res.body : (res.body && res.body.approvals) || [];
    return ok({ approvals, count: approvals.length });
  }

  if (mode === 'detail') {
    if (!input.approval_id) return fail('detail mode requires approval_id');
    const res = await pcGet(`/api/approvals/${encodeURIComponent(input.approval_id)}`);
    if (!res.ok) return fail(res.reason, { status: res.status });
    return ok({ approval: res.body });
  }

  return fail(`Unknown mode: ${mode}. Expected one of: pending, by_issue, detail`);
}

main().catch((err) => fail(err.message || String(err)));
