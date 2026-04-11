#!/usr/bin/env node
/**
 * paperclip-activity-feed.js
 * Nexus requirement 8, 22: proactive event stream for the 5-minute heartbeat.
 *
 * Wraps GET /api/companies/:companyId/activity. Paperclip's activity endpoint
 * does not natively accept a "since" cursor — it filters by agent/entity
 * instead — so this script pulls the filtered feed and does client-side
 * cutoff using the `since` input (ISO timestamp or epoch ms). The caller
 * (usually heartbeat-5min.lobster) passes the timestamp from the previous
 * heartbeat so each sweep only sees new events.
 *
 * Deterministic. Zero LLM.
 *
 * Input (stdin JSON):
 *   {
 *     since?: string | number,     // ISO timestamp or epoch ms — filter out older events
 *     agent_id?: string,           // filter to a single agent
 *     entity_type?: string,        // e.g. "issue", "approval", "goal"
 *     entity_id?: string           // filter to a single entity
 *   }
 *
 * Output:
 *   {ok: true, events: [...], count, cursor: <latest-timestamp>}
 */

const { getCompanyId, pcGet, readStdin, ok, fail } = require('./paperclip-http');

function parseCutoff(since) {
  if (since == null) return null;
  if (typeof since === 'number') return since;
  const parsed = Date.parse(since);
  return Number.isNaN(parsed) ? null : parsed;
}

function eventTimestamp(event) {
  const ts = event && (event.createdAt || event.occurredAt || event.timestamp || event.ts);
  if (!ts) return 0;
  if (typeof ts === 'number') return ts;
  const parsed = Date.parse(ts);
  return Number.isNaN(parsed) ? 0 : parsed;
}

async function main() {
  const input = await readStdin();
  const companyId = await getCompanyId();
  const query = {};
  if (input.agent_id) query.agentId = input.agent_id;
  if (input.entity_type) query.entityType = input.entity_type;
  if (input.entity_id) query.entityId = input.entity_id;

  const res = await pcGet(`/api/companies/${companyId}/activity`, query);
  if (!res.ok) return fail(res.reason, { status: res.status });

  const all = Array.isArray(res.body) ? res.body : (res.body && res.body.events) || [];
  const cutoff = parseCutoff(input.since);
  const filtered = cutoff == null
    ? all
    : all.filter((e) => eventTimestamp(e) > cutoff);

  const latestTs = filtered.reduce((max, e) => Math.max(max, eventTimestamp(e)), 0);

  return ok({
    events: filtered,
    count: filtered.length,
    cursor: latestTs > 0 ? new Date(latestTs).toISOString() : null,
  });
}

main().catch((err) => fail(err.message || String(err)));
