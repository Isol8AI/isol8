#!/usr/bin/env node
/**
 * nexus-goal-drift.js
 * Nexus requirement 26: detect issues that do not trace to an active goal.
 *
 * Lists every active issue in the company, lists every active goal, then
 * flags any issue whose project → goal ancestry does not land on an active
 * goal. The ancestry comes from /api/issues/:id which returns an `ancestors`
 * field (per the issues.ts route contract) — to keep this cheap, we read it
 * from the lightweight list response if present, or fetch the detail view
 * for issues whose list response lacks ancestry data.
 *
 * Deterministic. Zero LLM.
 *
 * Input (stdin JSON):
 *   { max_fetches?: number }   // cap on per-issue detail fetches, default 20
 *
 * Output:
 *   {
 *     ok: true,
 *     drifted: [{ issue_id, issue_title, assignee_agent_id, reason }],
 *     checked_count,
 *     active_goal_ids
 *   }
 */

const { pcGet, getCompanyId, readStdin, ok, fail } = require('./paperclip-http');

function collectActiveGoalIds(goals) {
  const ids = new Set();
  const walk = (node) => {
    if (!node) return;
    if (node.id && node.status !== 'archived' && node.archivedAt == null) {
      ids.add(node.id);
    }
    if (Array.isArray(node.children)) node.children.forEach(walk);
  };
  const arr = Array.isArray(goals) ? goals : (goals && goals.goals) || [];
  arr.forEach(walk);
  return ids;
}

function issueAncestorGoalIds(issue) {
  // issues.ts returns ancestors as part of GET /api/issues/:id
  const ancestors = issue.ancestors || issue.ancestry || [];
  const ids = [];
  for (const a of ancestors) {
    if (a && (a.type === 'goal' || a.kind === 'goal') && a.id) ids.push(a.id);
    if (a && a.goalId) ids.push(a.goalId);
  }
  // Some responses flatten project → goal linkage onto the issue directly
  if (issue.goalId) ids.push(issue.goalId);
  if (issue.projectGoalId) ids.push(issue.projectGoalId);
  return ids;
}

async function main() {
  const input = await readStdin();
  const maxFetches = input.max_fetches ?? 20;

  const companyId = await getCompanyId();
  const [issuesRes, goalsRes] = await Promise.all([
    pcGet(`/api/companies/${companyId}/issues`),
    pcGet(`/api/companies/${companyId}/goals`),
  ]);
  if (!issuesRes.ok) return fail(`issues list failed: ${issuesRes.reason}`, { status: issuesRes.status });
  if (!goalsRes.ok) return fail(`goals list failed: ${goalsRes.reason}`, { status: goalsRes.status });

  const activeGoalIds = collectActiveGoalIds(goalsRes.body);
  const issues = Array.isArray(issuesRes.body) ? issuesRes.body : (issuesRes.body && issuesRes.body.issues) || [];

  // Skip closed / cancelled issues — they don't need goal ancestry
  const active = issues.filter((i) => {
    const status = (i.status || '').toLowerCase();
    return status !== 'done' && status !== 'cancelled' && status !== 'closed' && status !== 'archived';
  });

  const drifted = [];
  let detailFetches = 0;

  for (const issue of active) {
    let ancestry = issueAncestorGoalIds(issue);
    if (ancestry.length === 0 && detailFetches < maxFetches) {
      // Fallback: fetch the detail view to see if ancestors are available there
      detailFetches += 1;
      const detailRes = await pcGet(`/api/issues/${encodeURIComponent(issue.id)}`);
      if (detailRes.ok && detailRes.body) {
        ancestry = issueAncestorGoalIds(detailRes.body);
      }
    }
    const linked = ancestry.some((id) => activeGoalIds.has(id));
    if (!linked) {
      drifted.push({
        issue_id: issue.id,
        issue_title: issue.title || null,
        assignee_agent_id: issue.assigneeAgentId || null,
        reason: ancestry.length === 0
          ? 'Issue has no goal ancestry'
          : `Issue ancestors ${ancestry.join(',')} do not include an active goal`,
      });
    }
  }

  return ok({
    drifted,
    drifted_count: drifted.length,
    checked_count: active.length,
    active_goal_ids: Array.from(activeGoalIds),
    detail_fetches_used: detailFetches,
  });
}

main().catch((err) => fail(err.message || String(err)));
