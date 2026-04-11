#!/usr/bin/env node
/**
 * nexus-approval-diff.js
 * Approval notification deduplicator across heartbeats.
 *
 * The 5-minute heartbeat polls /api/companies/:companyId/approvals?status=pending
 * every tick. Without dedup, the same pending approval would produce a Slack
 * notification every 5 minutes until the user acted on it. This script
 * diffs the current pending list against the set of approval IDs Nexus has
 * already surfaced to the user (persisted to fast-io between heartbeats) and
 * returns only the net-new ones.
 *
 * Pure function. No API calls. Zero LLM.
 *
 * Input (stdin JSON):
 *   {
 *     current_approvals: [{id, type, status, ...}],   // from paperclip-governance mode=pending
 *     notified_ids: string[]                           // from fast-io nexus-state/notified-approvals
 *   }
 *
 * Output:
 *   {
 *     ok: true,
 *     new_approvals: [{...}],           // approvals not in notified_ids
 *     updated_notified_ids: string[],   // notified_ids ∪ current_approvals.map(id) minus stale
 *     stale_count                       // notified IDs that are no longer pending (user acted on them)
 *   }
 */

const { readStdin, ok, fail } = require('./paperclip-http');

async function main() {
  const input = await readStdin();
  const current = Array.isArray(input.current_approvals) ? input.current_approvals : [];
  const notified = new Set(Array.isArray(input.notified_ids) ? input.notified_ids : []);

  const currentIds = new Set();
  const newApprovals = [];
  for (const approval of current) {
    if (!approval || !approval.id) continue;
    currentIds.add(approval.id);
    if (!notified.has(approval.id)) newApprovals.push(approval);
  }

  // Drop notified IDs that are no longer pending (the user acted on them)
  const updatedNotified = [];
  let staleCount = 0;
  for (const id of notified) {
    if (currentIds.has(id)) updatedNotified.push(id);
    else staleCount += 1;
  }
  // Add the new ones
  for (const approval of newApprovals) updatedNotified.push(approval.id);

  return ok({
    new_approvals: newApprovals,
    new_count: newApprovals.length,
    updated_notified_ids: updatedNotified,
    stale_count: staleCount,
  });
}

main().catch((err) => fail(err.message || String(err)));
