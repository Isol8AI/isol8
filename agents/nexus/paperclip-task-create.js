#!/usr/bin/env node
/**
 * paperclip-task-create.js
 * Nexus requirement 1, 2: delegate work to a specialist agent.
 *
 * Wraps POST /api/companies/:companyId/issues. The PRD talks about "tasks"
 * but Paperclip's domain object is "issue" — this script keeps the
 * Nexus-facing name (task) while pointing at the real endpoint.
 *
 * Dependencies live in Paperclip's deterministic layer via blockedByIssueIds,
 * so cross-agent execution order survives Nexus session restarts and heartbeat
 * boundaries — the LLM proposes, Paperclip enforces.
 *
 * Deterministic. Zero LLM.
 *
 * Input (stdin JSON):
 *   {
 *     title: string,                  // required
 *     assignee_agent_id: string,      // required — Paperclip agent ID
 *     description?: string,
 *     status?: string,                // default "todo"
 *     execution_policy?: string,      // e.g. "auto_execute", "require_approval"
 *     blocked_by?: string[]           // Paperclip issue IDs this issue depends on
 *   }
 *
 * Output:
 *   {ok: true, issue: {...}}
 *   {ok: false, reason: "..."}   // Paperclip rejected the create (budget, gate, policy)
 */

const { getCompanyId, pcPost, readStdin, ok, fail } = require('./paperclip-http');

async function main() {
  const input = await readStdin();
  if (!input.title || typeof input.title !== 'string') {
    return fail('Missing required field: title');
  }
  if (!input.assignee_agent_id || typeof input.assignee_agent_id !== 'string') {
    return fail('Missing required field: assignee_agent_id');
  }

  const companyId = await getCompanyId();
  const body = {
    title: input.title,
    description: input.description || '',
    status: input.status || 'todo',
    assigneeAgentId: input.assignee_agent_id,
  };
  if (input.execution_policy) body.executionPolicy = input.execution_policy;
  if (Array.isArray(input.blocked_by) && input.blocked_by.length > 0) {
    body.blockedByIssueIds = input.blocked_by;
  }

  const res = await pcPost(`/api/companies/${companyId}/issues`, body);
  if (!res.ok) {
    return fail(res.reason || `Paperclip rejected issue create (HTTP ${res.status})`, {
      status: res.status,
      paperclip_body: res.body,
    });
  }
  return ok({ issue: res.body });
}

main().catch((err) => fail(err.message || String(err)));
