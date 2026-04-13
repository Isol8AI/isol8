#!/usr/bin/env node
/**
 * ora-buffer-checker.js
 * Requirement 11: Flag back-to-back meeting chains exceeding buffer rules.
 *
 * Deterministic gap analysis. Zero LLM.
 */

async function main() {
  const input = await readStdin();
  if (!input) {
    process.stderr.write('No input provided');
    process.exit(1);
  }

  const events = (input.events || [])
    .filter(e => !e.is_focus_block && !e.is_all_day)
    .sort((a, b) => new Date(a.start) - new Date(b.start));
  const bufferMinutes = input.buffer_minutes || 15;

  const violations = [];
  let consecutiveCount = 1;
  let chainStart = events[0] || null;

  for (let i = 1; i < events.length; i++) {
    const prevEnd = new Date(events[i - 1].end);
    const currStart = new Date(events[i].start);
    const gapMinutes = (currStart - prevEnd) / (1000 * 60);

    if (gapMinutes < bufferMinutes) {
      consecutiveCount++;
    } else {
      if (consecutiveCount >= 3) {
        violations.push({
          chain_length: consecutiveCount,
          chain_start: chainStart?.title,
          chain_start_time: chainStart?.start,
          chain_end_time: events[i - 1].end,
          total_hours: Math.round((new Date(events[i - 1].end) - new Date(chainStart.start)) / (1000 * 60 * 60) * 10) / 10,
          events: events.slice(i - consecutiveCount, i).map(e => e.title)
        });
      }
      consecutiveCount = 1;
      chainStart = events[i];
    }
  }

  // Check final chain
  if (consecutiveCount >= 3) {
    violations.push({
      chain_length: consecutiveCount,
      chain_start: chainStart?.title,
      chain_start_time: chainStart?.start,
      chain_end_time: events[events.length - 1].end,
      total_hours: Math.round((new Date(events[events.length - 1].end) - new Date(chainStart.start)) / (1000 * 60 * 60) * 10) / 10,
      events: events.slice(events.length - consecutiveCount).map(e => e.title)
    });
  }

  // Also flag any two consecutive meetings with zero gap
  const zeroGaps = [];
  for (let i = 1; i < events.length; i++) {
    const prevEnd = new Date(events[i - 1].end);
    const currStart = new Date(events[i].start);
    const gapMinutes = (currStart - prevEnd) / (1000 * 60);
    if (gapMinutes <= 0) {
      zeroGaps.push({
        from: events[i - 1].title,
        to: events[i].title,
        overlap_minutes: Math.abs(Math.round(gapMinutes))
      });
    }
  }

  const result = {
    has_violations: violations.length > 0 || zeroGaps.length > 0,
    back_to_back_chains: violations,
    zero_gap_pairs: zeroGaps,
    total_meetings: events.length,
    buffer_minutes: bufferMinutes,
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
