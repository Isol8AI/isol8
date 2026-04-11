#!/usr/bin/env node
/**
 * nexus-fallback-router.js
 * Nexus requirement 4: static fallback routing when the circuit breaker trips.
 *
 * The PRD recommended making this deterministic instead of LLM-driven for the
 * common case so the LLM only fires on novel patterns. This script is the
 * lookup table. It takes a (failing_agent, task_type) pair and returns the
 * fallback agent, or null if no automatic fallback is defined — in which case
 * the pipeline surfaces to the user with "no automatic fallback, pick manually."
 *
 * The table is editable — this is where you add a mapping when you observe
 * the LLM consistently routing a failing-agent pattern to the same fallback
 * specialist (via capability-evolver feedback).
 *
 * Deterministic. Zero LLM.
 *
 * Input (stdin JSON):
 *   { failing_agent: string, task_type: string }
 *
 * Output:
 *   {ok: true, fallback: "<agent>", reason: "<string>"}
 *   {ok: true, fallback: null, reason: "no_automatic_fallback"}
 */

const { readStdin, ok, fail } = require('./paperclip-http');

// (failing_agent, task_type) → fallback_agent
// Keys are "<agent>:<task_type>" — lowercase, colon-separated.
// Task types mirror Paperclip issue classifications or Nexus-assigned routing tags.
const FALLBACK_TABLE = {
  // Pitch fails during a task that was really sourcing — route to Scout
  'pitch:sourcing': {
    fallback: 'scout',
    reason: 'Pitch is outreach-first; Scout is the sourcing specialist',
  },
  'pitch:lead-research': {
    fallback: 'lens',
    reason: 'Lead research is closer to Lens than to Pitch',
  },
  // Scout fails during outreach — Pitch can take over
  'scout:outreach': {
    fallback: 'pitch',
    reason: 'Outreach is Pitch\'s home domain; Scout is sourcing-first',
  },
  // Lens fails on light sourcing — Scout can substitute
  'lens:light-sourcing': {
    fallback: 'scout',
    reason: 'Light sourcing is Scout\'s domain',
  },
  // Pulse fails on research-heavy marketing — hand to Lens
  'pulse:research': {
    fallback: 'lens',
    reason: 'Lens is the research specialist; Pulse is marketing execution',
  },
  // Thread fails on outreach-style comms — Pitch can take over
  'thread:outreach': {
    fallback: 'pitch',
    reason: 'Outreach is Pitch',
  },
};

async function main() {
  const input = await readStdin();
  if (!input.failing_agent) return fail('Missing required field: failing_agent');
  if (!input.task_type) return fail('Missing required field: task_type');

  const key = `${String(input.failing_agent).toLowerCase()}:${String(input.task_type).toLowerCase()}`;
  const hit = FALLBACK_TABLE[key];

  if (!hit) {
    return ok({
      fallback: null,
      reason: 'no_automatic_fallback',
      matched_key: key,
    });
  }

  return ok({
    fallback: hit.fallback,
    reason: hit.reason,
    matched_key: key,
  });
}

main().catch((err) => fail(err.message || String(err)));
