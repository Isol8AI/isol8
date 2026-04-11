#!/usr/bin/env node
/**
 * nexus-circuit-breaker.js
 * Nexus requirement 15: pause delegation to an agent after 3 consecutive failures.
 *
 * Reads the recent activity feed, filters for issue-failed events grouped by
 * assigneeAgentId, and counts consecutive failures. If any agent has ≥ threshold
 * failures and is not already paused, emits a new pause event for the pipeline
 * to persist to fast-io at nexus-state/paused-agents and fire the circuit-breaker
 * notification template.
 *
 * Also emits "unpause candidates" — agents currently paused that have had
 * successful issues since they were paused — for the pipeline to consider
 * clearing.
 *
 * Deterministic. Zero LLM.
 *
 * Input (stdin JSON):
 *   {
 *     paused_agents?: { [agent_id]: { paused_at, reason, last_failure_id } },
 *     threshold?: number,   // default 3
 *     window_minutes?: number  // default 60 — only consider events in this window
 *   }
 *
 * Output:
 *   {
 *     ok: true,
 *     new_pauses: [{ agent_id, failure_count, last_failure, template_data }],
 *     unpause_candidates: [{ agent_id, success_count_since_pause }],
 *     failure_counts: { [agent_id]: count }
 *   }
 */

const { pcGet, getCompanyId, readStdin, ok, fail } = require('./paperclip-http');

function isFailure(event) {
  const action = (event.action || '').toLowerCase();
  return action === 'failed' || action === 'issue_failed' || action === 'error' || action === 'task_failed';
}

function isSuccess(event) {
  const action = (event.action || '').toLowerCase();
  return action === 'completed' || action === 'issue_completed' || action === 'done' || action === 'resolved';
}

function eventTimestamp(event) {
  const raw = event && (event.createdAt || event.occurredAt || event.timestamp);
  if (!raw) return 0;
  return typeof raw === 'number' ? raw : Date.parse(raw) || 0;
}

function agentIdOf(event) {
  return event.agentId || event.agent_id || (event.details && (event.details.agentId || event.details.assigneeAgentId)) || null;
}

async function main() {
  const input = await readStdin();
  const threshold = input.threshold ?? 3;
  const windowMinutes = input.window_minutes ?? 60;
  const pausedAgents = input.paused_agents || {};
  const cutoff = Date.now() - windowMinutes * 60 * 1000;

  const companyId = await getCompanyId();
  const res = await pcGet(`/api/companies/${companyId}/activity`, { entityType: 'issue' });
  if (!res.ok) return fail(res.reason, { status: res.status });

  const events = Array.isArray(res.body) ? res.body : (res.body && res.body.events) || [];
  // Sort newest first so "consecutive" counts from the most recent event backwards
  events.sort((a, b) => eventTimestamp(b) - eventTimestamp(a));

  const failureCounts = {};
  const lastFailure = {};
  const successCountsSincePause = {};

  for (const event of events) {
    const ts = eventTimestamp(event);
    if (ts < cutoff) break;
    const agentId = agentIdOf(event);
    if (!agentId) continue;

    if (isFailure(event)) {
      // Only count consecutive-from-most-recent failures (stop at first success)
      if (failureCounts[agentId] === undefined || failureCounts[agentId] > 0) {
        if (failureCounts[agentId] === undefined) failureCounts[agentId] = 0;
        // If we've already seen a success for this agent, don't keep counting failures
        if (successCountsSincePause[agentId] === undefined || successCountsSincePause[agentId] === 0) {
          failureCounts[agentId] = (failureCounts[agentId] || 0) + 1;
          if (!lastFailure[agentId]) lastFailure[agentId] = event;
        }
      }
    } else if (isSuccess(event)) {
      // If agent is currently paused, count successes since the pause timestamp
      const pauseState = pausedAgents[agentId];
      if (pauseState && pauseState.paused_at) {
        const pausedAt = typeof pauseState.paused_at === 'number'
          ? pauseState.paused_at
          : Date.parse(pauseState.paused_at) || 0;
        if (ts > pausedAt) {
          successCountsSincePause[agentId] = (successCountsSincePause[agentId] || 0) + 1;
        }
      }
      // Reset the consecutive failure counter for non-paused agents
      if (!pausedAgents[agentId]) {
        failureCounts[agentId] = 0;
      }
    }
  }

  const newPauses = [];
  for (const [agentId, count] of Object.entries(failureCounts)) {
    if (count >= threshold && !pausedAgents[agentId]) {
      const lf = lastFailure[agentId] || {};
      newPauses.push({
        agent_id: agentId,
        failure_count: count,
        last_failure: {
          id: lf.id || lf.entityId || null,
          reason: (lf.details && lf.details.reason) || lf.reason || null,
          timestamp: lf.createdAt || lf.occurredAt || null,
        },
        template_data: {
          agent: agentId,
          failures: count,
          last_failure_reason: (lf.details && lf.details.reason) || lf.reason || 'unknown',
          last_failure_id: lf.id || lf.entityId || null,
        },
      });
    }
  }

  const unpauseCandidates = [];
  for (const [agentId, count] of Object.entries(successCountsSincePause)) {
    if (count > 0 && pausedAgents[agentId]) {
      unpauseCandidates.push({ agent_id: agentId, success_count_since_pause: count });
    }
  }

  return ok({
    new_pauses: newPauses,
    unpause_candidates: unpauseCandidates,
    failure_counts: failureCounts,
    window_minutes: windowMinutes,
    threshold,
  });
}

main().catch((err) => fail(err.message || String(err)));
