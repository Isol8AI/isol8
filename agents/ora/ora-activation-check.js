#!/usr/bin/env node
/**
 * ora-activation-check.js
 * Requirements 1, 2, 5, 6: Validate calendar connections and scheduling rules.
 *
 * Deterministic. Zero LLM.
 */

async function main() {
  const input = await readStdin();
  const checks = [];

  // Requirement 1: At least one calendar connected
  const calendars = input?.connected_calendars || [];
  if (calendars.length === 0) {
    checks.push({
      check: 'calendar_connection',
      pass: false,
      severity: 'blocker',
      reason: 'No calendar connected. Ora cannot operate without calendar access — fragmented visibility is the primary cause of double-booking.',
      remediation: 'Connect at least one calendar: caldav-calendar for Google/iCloud, ms365 for Outlook, or calctl for Apple Calendar.'
    });
  } else {
    checks.push({
      check: 'calendar_connection',
      pass: true,
      calendars_connected: calendars.length,
      platforms: calendars.map(c => c.platform)
    });
  }

  // Requirement 5: Scheduling rules configured
  const rules = input?.scheduling_rules;
  if (!rules) {
    checks.push({
      check: 'scheduling_rules',
      pass: false,
      severity: 'blocker',
      reason: 'No scheduling rules configured. Without rules, Ora cannot protect your time — Motion\'s documented failure is back-to-back meetings without breaks because rules weren\'t set up.',
      remediation: 'Configure: earliest start time, latest end time, buffer between meetings, max meetings per day, no-meeting days, and focus block preferences.'
    });
  } else {
    const required = ['earliest_start', 'latest_end', 'buffer_minutes'];
    const missing = required.filter(r => rules[r] === undefined || rules[r] === null);
    if (missing.length > 0) {
      checks.push({
        check: 'scheduling_rules',
        pass: false,
        severity: 'blocker',
        reason: `Scheduling rules incomplete. Missing: ${missing.join(', ')}`,
        remediation: 'Complete the scheduling rules configuration.'
      });
    } else {
      checks.push({ check: 'scheduling_rules', pass: true });
    }
  }

  // Conferencing platform
  const conferencing = input?.conferencing;
  if (!conferencing || !conferencing.platform) {
    checks.push({
      check: 'conferencing',
      pass: false,
      severity: 'warning',
      reason: 'No default conferencing platform configured. Ora won\'t be able to auto-add video links to meetings.',
      remediation: 'Set a default: zoom, google_meet, or microsoft_teams.'
    });
  } else {
    checks.push({ check: 'conferencing', pass: true, platform: conferencing.platform });
  }

  // Webhook configuration
  const webhooks = input?.webhooks;
  if (!webhooks || !webhooks.calendar_push) {
    checks.push({
      check: 'webhooks',
      pass: false,
      severity: 'warning',
      reason: 'Calendar webhooks not configured. Ora will use polling instead of real-time sync, which risks stale data and race conditions.',
      remediation: 'Configure push notifications for connected calendar platforms.'
    });
  } else {
    checks.push({ check: 'webhooks', pass: true });
  }

  const blockers = checks.filter(c => !c.pass && c.severity === 'blocker');
  const result = {
    pass: blockers.length === 0,
    blockers,
    warnings: checks.filter(c => !c.pass && c.severity === 'warning'),
    checks,
    timestamp: new Date().toISOString()
  };

  process.stdout.write(JSON.stringify(result));
  process.exit(blockers.length === 0 ? 0 : 1);
}

function readStdin() {
  return new Promise((resolve) => {
    let data = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', chunk => data += chunk);
    process.stdin.on('end', () => {
      try { resolve(JSON.parse(data)); }
      catch { resolve(null); }
    });
    if (process.stdin.isTTY) resolve(null);
  });
}

if (require.main === module) {
  main().catch(err => {
    process.stderr.write(err.message);
    process.exit(1);
  });
}
