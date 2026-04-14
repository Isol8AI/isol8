#!/usr/bin/env node
/**
 * pulse-email-analyzer.js
 * Requirement 33: Email performance pattern analysis. Hybrid: ~70% deterministic.
 */

async function main() {
  const input = await readStdin();
  if (!input) { process.stderr.write('No input'); process.exit(1); }

  const sends = input.email_sends || [];
  if (sends.length === 0) {
    process.stdout.write(JSON.stringify({ patterns: [], note: 'No email data for this period.' }));
    return;
  }

  // Metric calculations — all deterministic
  const avgOpenRate = avg(sends.map(s => s.open_rate).filter(Boolean));
  const avgClickRate = avg(sends.map(s => s.click_rate).filter(Boolean));
  const avgUnsubRate = avg(sends.map(s => s.unsub_rate).filter(Boolean));

  // Top performer
  const bestByClicks = [...sends].sort((a, b) => (b.click_rate || 0) - (a.click_rate || 0))[0];
  const worstByClicks = [...sends].sort((a, b) => (a.click_rate || 0) - (b.click_rate || 0))[0];

  // Subject line pattern analysis — deterministic
  const subjectPatterns = {
    question_format: sends.filter(s => (s.subject || '').includes('?')),
    number_format: sends.filter(s => /\d/.test(s.subject || '')),
    short_subjects: sends.filter(s => (s.subject || '').length < 40),
    long_subjects: sends.filter(s => (s.subject || '').length >= 60),
    personalized: sends.filter(s => (s.subject || '').includes('{') || (s.subject || '').toLowerCase().includes('you'))
  };

  const patternPerformance = {};
  for (const [pattern, matching] of Object.entries(subjectPatterns)) {
    if (matching.length >= 2) {
      patternPerformance[pattern] = {
        count: matching.length,
        avg_open_rate: avg(matching.map(s => s.open_rate).filter(Boolean)),
        avg_click_rate: avg(matching.map(s => s.click_rate).filter(Boolean)),
        vs_average: {
          open_rate_diff: avg(matching.map(s => s.open_rate).filter(Boolean)) - avgOpenRate,
          click_rate_diff: avg(matching.map(s => s.click_rate).filter(Boolean)) - avgClickRate
        }
      };
    }
  }

  // Segment performance
  const bySegment = {};
  for (const send of sends) {
    const seg = send.segment || 'all';
    if (!bySegment[seg]) bySegment[seg] = [];
    bySegment[seg].push(send);
  }
  const segmentPerformance = {};
  for (const [seg, segSends] of Object.entries(bySegment)) {
    segmentPerformance[seg] = {
      send_count: segSends.length,
      avg_open_rate: avg(segSends.map(s => s.open_rate).filter(Boolean)),
      avg_click_rate: avg(segSends.map(s => s.click_rate).filter(Boolean)),
      avg_unsub_rate: avg(segSends.map(s => s.unsub_rate).filter(Boolean))
    };
  }

  // Sequence drop-off — where engagement falls
  const sequenceSends = sends.filter(s => s.sequence_position !== undefined)
    .sort((a, b) => a.sequence_position - b.sequence_position);
  const dropOff = sequenceSends.length > 1
    ? sequenceSends.map((s, i) => ({
        position: s.sequence_position,
        open_rate: s.open_rate,
        click_rate: s.click_rate,
        drop_from_prior: i > 0 ? s.open_rate - sequenceSends[i - 1].open_rate : 0
      }))
    : null;

  const result = {
    summary: {
      total_sends: sends.length,
      avg_open_rate: Math.round(avgOpenRate * 1000) / 10,
      avg_click_rate: Math.round(avgClickRate * 1000) / 10,
      avg_unsub_rate: Math.round(avgUnsubRate * 10000) / 100
    },
    best_performer: bestByClicks ? { subject: bestByClicks.subject, click_rate: bestByClicks.click_rate, segment: bestByClicks.segment } : null,
    worst_performer: worstByClicks ? { subject: worstByClicks.subject, click_rate: worstByClicks.click_rate, segment: worstByClicks.segment } : null,
    subject_patterns: patternPerformance,
    segment_performance: segmentPerformance,
    sequence_drop_off: dropOff,
    needs_llm_synthesis: true, // Pipeline uses llm-task to synthesize patterns into insight
    timestamp: new Date().toISOString()
  };

  process.stdout.write(JSON.stringify(result));
}

function avg(arr) { return arr.length > 0 ? arr.reduce((a, b) => a + b, 0) / arr.length : 0; }

function readStdin() {
  return new Promise((resolve) => {
    let data = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', chunk => data += chunk);
    process.stdin.on('end', () => { try { resolve(JSON.parse(data)); } catch { resolve(null); } });
    if (process.stdin.isTTY) resolve(null);
  });
}

if (require.main === module) { main().catch(err => { process.stderr.write(err.message); process.exit(1); }); }
