#!/usr/bin/env node
/**
 * ora-meeting-quality-checker.js
 * Requirement 34: Flag meetings with no agenda. Adaptive suppression for recurring internal.
 *
 * Deterministic. Zero LLM.
 */

async function main() {
  const input = await readStdin();
  if (!input) {
    process.stderr.write('No input provided');
    process.exit(1);
  }

  const meetings = input.meetings || [];
  const dismissalHistory = input.dismissal_history || {};
  const flags = [];

  for (const meeting of meetings) {
    const hasAgenda = meeting.description && meeting.description.trim().length > 10;
    const hasNotes = meeting.notes && meeting.notes.trim().length > 0;

    if (hasAgenda || hasNotes) continue;

    // Check if user has dismissed this flag for this recurring meeting before
    const meetingKey = meeting.recurring_id || meeting.title?.toLowerCase();
    const dismissCount = dismissalHistory[meetingKey] || 0;

    // Suppress after 3 dismissals for the same recurring meeting
    if (dismissCount >= 3) continue;

    const isExternal = meeting.attendees?.some(a => a.external);
    const isRecurring = !!meeting.recurring_id;

    flags.push({
      meeting_title: meeting.title,
      start: meeting.start,
      attendees: (meeting.attendees || []).length,
      is_external: isExternal,
      is_recurring: isRecurring,
      severity: isExternal ? 'high' : 'info',
      prior_dismissals: dismissCount,
      message: isExternal
        ? `Your ${meeting.title} with external attendees has no agenda. Meetings without agendas run longer and produce fewer decisions.`
        : `Your ${meeting.title} has no agenda. Want to add one?`
    });
  }

  const result = {
    flagged: flags,
    flagged_count: flags.length,
    external_no_agenda: flags.filter(f => f.is_external).length,
    timestamp: new Date().toISOString()
  };

  process.stdout.write(JSON.stringify(result));
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
