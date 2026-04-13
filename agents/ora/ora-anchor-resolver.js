#!/usr/bin/env node
/**
 * ora-anchor-resolver.js
 * Requirement 30: Resolve relative time references by looking up anchor events.
 *
 * Deterministic title matching. Agent loop escape for fuzzy resolution.
 */

async function main() {
  const input = await readStdin();
  if (!input) {
    process.stderr.write('No input provided');
    process.exit(1);
  }

  const reference = (input.reference || '').toLowerCase();
  const events = input.upcoming_events || [];

  // Try exact title match first
  let match = events.find(e =>
    (e.title || '').toLowerCase() === reference
  );

  // Try partial title match
  if (!match) {
    match = events.find(e =>
      (e.title || '').toLowerCase().includes(reference) ||
      reference.includes((e.title || '').toLowerCase())
    );
  }

  // Try keyword extraction — "before the board meeting" → search for "board"
  if (!match) {
    const keywords = reference.replace(/before|after|the|our|my|next|this/gi, '').trim().split(/\s+/);
    for (const keyword of keywords) {
      if (keyword.length < 3) continue;
      match = events.find(e =>
        (e.title || '').toLowerCase().includes(keyword)
      );
      if (match) break;
    }
  }

  if (match) {
    process.stdout.write(JSON.stringify({
      resolved: true,
      anchor_event: {
        title: match.title,
        start: match.start,
        end: match.end,
        date: new Date(match.start).toISOString().split('T')[0]
      },
      match_type: 'calendar_lookup',
      needs_agent_loop: false
    }));
  } else {
    // Escape hatch: no title match found — agent loop should search
    // by attendee names, date context, and broader conversation context
    process.stdout.write(JSON.stringify({
      resolved: false,
      reference,
      searched_events: events.length,
      needs_agent_loop: true,
      agent_loop_context: `Could not find "${reference}" by title search across ${events.length} upcoming events. The agent loop should try: searching by attendee names mentioned in the reference, expanding the date range, checking past events for recurring meetings, or asking the user to clarify which event they mean.`
    }));
  }
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
