#!/usr/bin/env node
/**
 * nexus-activation-check.js
 * Bootstrap validator — run at the end of BOOTSTRAP.md.
 *
 * Returns {ok: true, pass: true} if every gate passes, or {ok: true, pass: false,
 * blockers: [...]} so bootstrap can stop and tell the user what is missing.
 *
 * Pipeline-accessible state (routing map, budget baseline, pending approvals
 * baseline, notify channel, fallback table freshness) is passed in via stdin
 * from the pipeline — this script does not call fast-io directly.
 *
 * Deterministic. Zero LLM.
 *
 * Input (stdin JSON — all fields optional):
 *   {
 *     state?: {
 *       routing_map_present?: boolean,
 *       budget_baseline_present?: boolean,
 *       pending_approvals_baseline_present?: boolean,
 *       notify_channel_present?: boolean
 *     },
 *     cron_registered?: { heartbeat?: boolean, daily_digest?: boolean, weekly_review?: boolean }
 *   }
 *
 * Output:
 *   {ok: true, pass: boolean, blockers: [...], warnings: [...], checks: [...]}
 */

const fs = require('fs');
const { pcGet, getCompanyId, readStdin, ok } = require('./paperclip-http');

const KEY_PATH = process.env.PAPERCLIP_BOARD_KEY_PATH || '/home/node/.openclaw/.paperclip/board-key';
const BASE_URL = process.env.PAPERCLIP_BASE_URL || 'http://localhost:3100';

async function main() {
  const input = await readStdin();
  const blockers = [];
  const warnings = [];
  const checks = [];

  // Env vars
  if (!process.env.PAPERCLIP_BOARD_KEY_PATH) {
    warnings.push({ check: 'env:PAPERCLIP_BOARD_KEY_PATH', detail: `Unset — using default ${KEY_PATH}` });
  } else {
    checks.push({ check: 'env:PAPERCLIP_BOARD_KEY_PATH', pass: true });
  }
  if (!process.env.PAPERCLIP_BASE_URL) {
    warnings.push({ check: 'env:PAPERCLIP_BASE_URL', detail: `Unset — using default ${BASE_URL}` });
  } else {
    checks.push({ check: 'env:PAPERCLIP_BASE_URL', pass: true });
  }

  // Board key file
  try {
    const key = fs.readFileSync(KEY_PATH, 'utf-8').trim();
    if (!key) {
      blockers.push({ check: 'file:board-key', detail: `${KEY_PATH} is empty` });
    } else {
      checks.push({ check: 'file:board-key', pass: true, bytes: key.length });
    }
  } catch (err) {
    blockers.push({
      check: 'file:board-key',
      detail: `${KEY_PATH} not readable: ${err.message}. Is Paperclip provisioned?`,
    });
  }

  // Paperclip sidecar health — only if board key is readable
  if (blockers.length === 0) {
    try {
      const health = await pcGet('/api/health');
      if (health.ok) {
        checks.push({ check: 'http:paperclip-health', pass: true });
      } else {
        blockers.push({
          check: 'http:paperclip-health',
          detail: `${BASE_URL}/api/health returned ${health.status}: ${health.reason}`,
        });
      }
    } catch (err) {
      blockers.push({
        check: 'http:paperclip-health',
        detail: `${BASE_URL}/api/health unreachable: ${err.message}`,
      });
    }
  }

  // Resolve companyId + verify at least one agent exists
  if (blockers.length === 0) {
    try {
      const companyId = await getCompanyId();
      checks.push({ check: 'api:company-id', pass: true, value: companyId });
      const agents = await pcGet(`/api/companies/${companyId}/agents`);
      if (!agents.ok) {
        blockers.push({
          check: 'api:agents-list',
          detail: `companies/${companyId}/agents returned ${agents.status}: ${agents.reason}`,
        });
      } else {
        const list = Array.isArray(agents.body) ? agents.body : (agents.body && agents.body.agents) || [];
        if (list.length === 0) {
          warnings.push({
            check: 'api:agents-list',
            detail: 'No specialist agents deployed yet — routing will have nothing to route to',
          });
        } else {
          checks.push({ check: 'api:agents-list', pass: true, count: list.length });
        }
      }
    } catch (err) {
      blockers.push({ check: 'api:company-id', detail: err.message });
    }
  }

  // Pipeline-passed state validation
  const state = input.state || {};
  for (const [key, label] of Object.entries({
    routing_map_present: 'fastio:routing-map',
    budget_baseline_present: 'fastio:budget-baseline',
    pending_approvals_baseline_present: 'fastio:pending-approvals-baseline',
    notify_channel_present: 'fastio:notify-channel',
  })) {
    if (state[key] === true) {
      checks.push({ check: label, pass: true });
    } else if (state[key] === false) {
      blockers.push({ check: label, detail: 'Bootstrap step skipped or failed — re-run the corresponding step' });
    } else {
      warnings.push({ check: label, detail: 'Not reported by pipeline — could not verify' });
    }
  }

  // Cron registration (best-effort — pipeline tells us)
  const cron = input.cron_registered || {};
  for (const [key, label] of Object.entries({
    heartbeat: 'cron:nexus-heartbeat',
    daily_digest: 'cron:nexus-daily-digest',
    weekly_review: 'cron:nexus-weekly-review',
  })) {
    if (cron[key] === true) checks.push({ check: label, pass: true });
    else if (cron[key] === false) blockers.push({ check: label, detail: 'Cron job not registered' });
    else warnings.push({ check: label, detail: 'Not reported by pipeline — could not verify' });
  }

  return ok({
    pass: blockers.length === 0,
    blockers,
    warnings,
    checks,
    timestamp: new Date().toISOString(),
  });
}

main().catch((err) => {
  process.stdout.write(JSON.stringify({ ok: false, reason: err.message || String(err) }) + '\n');
  process.exit(1);
});
