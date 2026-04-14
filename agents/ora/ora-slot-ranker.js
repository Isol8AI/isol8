#!/usr/bin/env node
/**
 * ora-slot-ranker.js
 * Requirements 24, 26: Rank available slots, present trade-offs when no perfect option.
 *
 * Deterministic scoring. Agent loop escape hatch when no good options exist.
 */

function rankSlots(slots, participants, userPreferences) {
  const preferredTime = userPreferences.preferred_time || 'morning'; // morning, afternoon, any
  const preferMorning = preferredTime === 'morning';

  const scored = slots.map(slot => {
    const slotStart = new Date(slot.start);
    const slotHour = slotStart.getHours() + slotStart.getMinutes() / 60;
    let score = 100;
    const tradeoffs = [];

    // Dimension 1: Within all participants' working hours (40 points)
    let allWithinHours = true;
    for (const p of participants) {
      const pLocalHour = slot.participant_local_times?.[p.email]?.hour;
      const pStart = parseTimeToHour(p.working_hours?.start || '09:00');
      const pEnd = parseTimeToHour(p.working_hours?.end || '18:00');

      if (pLocalHour !== undefined && (pLocalHour < pStart || pLocalHour >= pEnd)) {
        allWithinHours = false;
        score -= 25;
        tradeoffs.push({
          type: 'outside_working_hours',
          participant: p.name || p.email,
          their_local_time: slot.participant_local_times?.[p.email]?.formatted,
          detail: `Falls at ${slot.participant_local_times?.[p.email]?.formatted} for ${p.name} — outside their ${p.working_hours?.start || '9:00'}-${p.working_hours?.end || '18:00'} working hours.`
        });
      }
    }

    // Dimension 2: Preferred time of day (20 points)
    if (preferMorning && slotHour >= 13) {
      score -= 10;
      tradeoffs.push({ type: 'not_preferred_time', detail: 'Afternoon slot — you prefer mornings.' });
    }
    if (!preferMorning && preferredTime === 'afternoon' && slotHour < 12) {
      score -= 10;
      tradeoffs.push({ type: 'not_preferred_time', detail: 'Morning slot — you prefer afternoons.' });
    }

    // Dimension 3: Buffer compliance (20 points)
    if (slot.buffer_violation) {
      score -= 15;
      tradeoffs.push({
        type: 'buffer_violation',
        detail: `${slot.buffer_violation.gap_minutes} min gap with "${slot.buffer_violation.adjacent_meeting}" — below your ${slot.buffer_violation.required_minutes} min buffer.`
      });
    }

    // Dimension 4: Focus block displacement (20 points)
    if (slot.displaces_focus_block) {
      score -= 20;
      tradeoffs.push({
        type: 'focus_block_displacement',
        detail: `Requires moving your ${slot.displaces_focus_block.start}-${slot.displaces_focus_block.end} focus block.`
      });
    }

    // Dimension 5: Day load (10 points)
    if (slot.day_meeting_count >= (userPreferences.max_meetings_per_day || 6)) {
      score -= 10;
      tradeoffs.push({
        type: 'heavy_day',
        detail: `Already ${slot.day_meeting_count} meetings that day — at your daily limit.`
      });
    }

    return {
      ...slot,
      score: Math.max(0, score),
      tradeoffs,
      is_perfect: tradeoffs.length === 0,
      all_within_hours: allWithinHours
    };
  });

  // Sort by score descending
  const ranked = scored.sort((a, b) => b.score - a.score);

  // Determine if we have any good options
  const perfectSlots = ranked.filter(s => s.is_perfect);
  const goodSlots = ranked.filter(s => s.score >= 70);
  const bestAvailable = ranked.slice(0, 3);

  // Escape hatch: when no slot scores above 50, the script's model
  // can't find a good answer. Route to agent loop for creative solutions
  // (async meeting, split into smaller meetings, suggest a different week)
  const needsAgentLoop = ranked.length === 0 || (ranked[0]?.score || 0) < 50;

  return {
    ranked: bestAvailable,
    perfect_options: perfectSlots.length,
    good_options: goodSlots.length,
    total_evaluated: slots.length,
    scenario: perfectSlots.length > 0 ? 'perfect_match' :
              goodSlots.length > 0 ? 'good_with_tradeoffs' :
              ranked.length > 0 ? 'all_have_tradeoffs' :
              'no_options',
    needs_agent_loop: needsAgentLoop,
    agent_loop_reason: needsAgentLoop
      ? 'No slot scores above 50. The standard ranking can\'t find a good option. Consider: async meeting, splitting into smaller sessions, suggesting a different week, or asking which constraint the user is most willing to relax.'
      : null,
    timestamp: new Date().toISOString()
  };
}

function parseTimeToHour(timeStr) {
  const [h, m] = (timeStr || '09:00').split(':').map(Number);
  return h + (m || 0) / 60;
}

async function main() {
  const input = await readStdin();
  if (!input) {
    process.stderr.write('No input provided');
    process.exit(1);
  }

  const result = rankSlots(
    input.slots || [],
    input.participants || [],
    input.user_preferences || {}
  );

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

module.exports = { rankSlots };

if (require.main === module) {
  main().catch(err => {
    process.stderr.write(err.message);
    process.exit(1);
  });
}
