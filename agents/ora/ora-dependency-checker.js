#!/usr/bin/env node
/**
 * ora-dependency-checker.js
 * Requirement 42: Flag dependent events on cancellation.
 *
 * Deterministic scanning by attendee, time proximity, and title. Zero LLM.
 */

async function main() {
  const input = await readStdin();
  if (!input) {
    process.stderr.write('No input provided');
    process.exit(1);
  }

  const targetEvent = input.event || {};
  const allEvents = input.all_events || [];
  const targetStart = new Date(targetEvent.start);
  const targetEnd = new Date(targetEvent.end);
  const targetDate = targetStart.toISOString().split('T')[0];
  const targetAttendees = (targetEvent.attendees || []).map(a => (a.email || a).toLowerCase());
  const targetTitle = (targetEvent.title || '').toLowerCase();

  const dependencies = [];

  for (const event of allEvents) {
    if (event.id === targetEvent.id) continue;
    const eventStart = new Date(event.start);
    const eventDate = eventStart.toISOString().split('T')[0];
    const eventTitle = (event.title || '').toLowerCase();
    const eventAttendees = (event.attendees || []).map(a => (a.email || a).toLowerCase());

    // Check 1: Prep session — same day, earlier, overlapping attendees, title contains "prep"
    if (eventDate === targetDate && eventStart < targetStart) {
      const hasOverlap = eventAttendees.some(a => targetAttendees.includes(a));
      const isPrepLike = eventTitle.includes('prep') || eventTitle.includes('preparation') ||
                         eventTitle.includes('briefing') || eventTitle.includes('pre-meeting');
      if (hasOverlap || isPrepLike) {
        dependencies.push({
          type: 'prep_session',
          event: { title: event.title, start: event.start, end: event.end },
          reason: isPrepLike ? 'Pre-meeting session for the cancelled event' : 'Same-day earlier meeting with overlapping attendees'
        });
      }
    }

    // Check 2: Follow-up — same day or next day, later, overlapping attendees, title contains "follow"
    const nextDay = new Date(targetStart);
    nextDay.setDate(nextDay.getDate() + 1);
    const nextDayStr = nextDay.toISOString().split('T')[0];

    if ((eventDate === targetDate && eventStart > targetEnd) || eventDate === nextDayStr) {
      const hasOverlap = eventAttendees.some(a => targetAttendees.includes(a));
      const isFollowUp = eventTitle.includes('follow') || eventTitle.includes('debrief') ||
                         eventTitle.includes('recap') || eventTitle.includes('next steps');
      if (hasOverlap && isFollowUp) {
        dependencies.push({
          type: 'follow_up',
          event: { title: event.title, start: event.start, end: event.end },
          reason: 'Follow-up meeting for the cancelled event'
        });
      }
    }

    // Check 3: Travel blocks — same day, title contains "travel" or "commute"
    if (eventDate === targetDate) {
      const isTravelBlock = eventTitle.includes('travel') || eventTitle.includes('commute') ||
                            eventTitle.includes('drive to') || eventTitle.includes('flight');
      if (isTravelBlock) {
        dependencies.push({
          type: 'travel_block',
          event: { title: event.title, start: event.start, end: event.end },
          reason: 'Travel block associated with this meeting'
        });
      }
    }

    // Check 4: Same recurring series
    if (targetEvent.recurring_id && event.recurring_id === targetEvent.recurring_id && event.id !== targetEvent.id) {
      dependencies.push({
        type: 'recurring_series',
        event: { title: event.title, start: event.start, end: event.end },
        reason: 'Part of the same recurring series — cancelling one may affect the whole series'
      });
      break; // Only flag the series once
    }
  }

  const result = {
    has_dependencies: dependencies.length > 0,
    dependencies,
    target_event: { title: targetEvent.title, start: targetEvent.start },
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
