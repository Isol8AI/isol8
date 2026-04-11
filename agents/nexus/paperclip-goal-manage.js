#!/usr/bin/env node
/**
 * paperclip-goal-manage.js
 * Nexus requirements 25, 26: goal hierarchy CRUD + drift detection support.
 *
 * Wraps Paperclip's goals endpoints. Create/update/delete are gated by the
 * agent's operating instructions — Nexus must surface every proposed goal
 * change to the user for approval before calling this script in a mutating
 * mode. List and get are autonomous.
 *
 * Deterministic. Zero LLM.
 *
 * Input (stdin JSON):
 *   { action: "list" }
 *   { action: "get",    id: "<goal-id>" }
 *   { action: "create", data: { title, level, ...createGoalSchema fields } }
 *   { action: "update", id: "<goal-id>", data: { ...updateGoalSchema fields } }
 *   { action: "delete", id: "<goal-id>" }
 */

const { getCompanyId, pcGet, pcPost, pcPatch, pcDelete, readStdin, ok, fail } = require('./paperclip-http');

async function main() {
  const input = await readStdin();
  const action = input.action || 'list';
  const companyId = await getCompanyId();

  if (action === 'list') {
    const res = await pcGet(`/api/companies/${companyId}/goals`);
    if (!res.ok) return fail(res.reason, { status: res.status });
    const goals = Array.isArray(res.body) ? res.body : (res.body && res.body.goals) || [];
    return ok({ goals, count: goals.length });
  }

  if (action === 'get') {
    if (!input.id) return fail('get action requires id');
    const res = await pcGet(`/api/goals/${encodeURIComponent(input.id)}`);
    if (!res.ok) return fail(res.reason, { status: res.status });
    return ok({ goal: res.body });
  }

  if (action === 'create') {
    if (!input.data || typeof input.data !== 'object') {
      return fail('create action requires data object');
    }
    if (!input.data.title) return fail('create action requires data.title');
    const res = await pcPost(`/api/companies/${companyId}/goals`, input.data);
    if (!res.ok) return fail(res.reason, { status: res.status, paperclip_body: res.body });
    return ok({ goal: res.body });
  }

  if (action === 'update') {
    if (!input.id) return fail('update action requires id');
    if (!input.data || typeof input.data !== 'object') {
      return fail('update action requires data object');
    }
    const res = await pcPatch(`/api/goals/${encodeURIComponent(input.id)}`, input.data);
    if (!res.ok) return fail(res.reason, { status: res.status, paperclip_body: res.body });
    return ok({ goal: res.body });
  }

  if (action === 'delete') {
    if (!input.id) return fail('delete action requires id');
    const res = await pcDelete(`/api/goals/${encodeURIComponent(input.id)}`);
    if (!res.ok) return fail(res.reason, { status: res.status });
    return ok({ goal: res.body });
  }

  return fail(`Unknown action: ${action}. Expected one of: list, get, create, update, delete`);
}

main().catch((err) => fail(err.message || String(err)));
