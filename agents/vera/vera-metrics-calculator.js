#!/usr/bin/env node
/**
 * vera-metrics-calculator.js
 * Requirements 45, 47: Weekly metrics computation with escalation type breakdown.
 *
 * Computes: resolution rate, escalation rate, re-contact rate, CSAT,
 * response time, KB gap count, and confidence/sentiment/request escalation rates separately.
 * Deterministic math. Zero LLM.
 */

async function main() {
  const input = await readStdin();
  if (!input) {
    process.stderr.write('No input provided');
    process.exit(1);
  }

  const tickets = input.tickets || [];
  const csatScores = input.csat_scores || [];
  const kbGaps = input.kb_gaps || [];
  const escalations = input.escalations || [];
  const period = input.period || '7d';

  const totalTickets = tickets.length;
  if (totalTickets === 0) {
    process.stdout.write(JSON.stringify({
      period,
      total_tickets: 0,
      note: 'No tickets in reporting period.',
      timestamp: new Date().toISOString()
    }));
    return;
  }

  // --- Resolution rate (autonomous vs escalated) ---
  const autonomousResolved = tickets.filter(t =>
    t.resolution_method === 'autonomous' && t.status === 'resolved'
  ).length;
  const humanResolved = tickets.filter(t =>
    t.resolution_method === 'human' && t.status === 'resolved'
  ).length;
  const unresolved = tickets.filter(t => t.status !== 'resolved').length;

  const autonomousResolutionRate = totalTickets > 0
    ? Math.round((autonomousResolved / totalTickets) * 1000) / 10
    : 0;

  // --- Escalation rate ---
  const totalEscalated = escalations.length;
  const escalationRate = totalTickets > 0
    ? Math.round((totalEscalated / totalTickets) * 1000) / 10
    : 0;

  // --- Requirement 47: Escalation type breakdown ---
  const escalationByTrigger = {};
  for (const esc of escalations) {
    const trigger = esc.trigger || 'unknown';
    if (!escalationByTrigger[trigger]) escalationByTrigger[trigger] = 0;
    escalationByTrigger[trigger]++;
  }
  const escalationRateByTrigger = {};
  for (const [trigger, count] of Object.entries(escalationByTrigger)) {
    escalationRateByTrigger[trigger] = {
      count,
      rate: Math.round((count / totalTickets) * 1000) / 10,
      pct_of_escalations: totalEscalated > 0
        ? Math.round((count / totalEscalated) * 1000) / 10
        : 0
    };
  }

  // --- Re-contact rate (same customer, same issue within 7 days) ---
  const recontacts = tickets.filter(t => t.is_recontact).length;
  const recontactRate = totalTickets > 0
    ? Math.round((recontacts / totalTickets) * 1000) / 10
    : 0;

  // --- CSAT ---
  const csatValues = csatScores.map(c => c.score).filter(s => s !== null && s !== undefined);
  const avgCsat = csatValues.length > 0
    ? Math.round((csatValues.reduce((a, b) => a + b, 0) / csatValues.length) * 10) / 10
    : null;
  const csatResponseRate = totalTickets > 0
    ? Math.round((csatValues.length / totalTickets) * 1000) / 10
    : 0;
  const belowThreshold = csatValues.filter(s => s <= (input.csat_threshold || 3)).length;

  // --- Response time ---
  const responseTimes = tickets
    .map(t => t.first_response_ms)
    .filter(t => t !== null && t !== undefined);
  const avgResponseTime = responseTimes.length > 0
    ? Math.round(responseTimes.reduce((a, b) => a + b, 0) / responseTimes.length)
    : null;
  const avgResponseTimeSeconds = avgResponseTime ? Math.round(avgResponseTime / 1000) : null;

  // --- KB gaps ---
  const kbGapCount = kbGaps.length;
  const topGaps = groupAndCount(kbGaps.map(g => g.topic || g.question || 'unknown'))
    .slice(0, 10);

  // --- Build report ---
  const report = {
    period,
    total_tickets: totalTickets,

    resolution: {
      autonomous_resolved: autonomousResolved,
      human_resolved: humanResolved,
      unresolved,
      autonomous_resolution_rate: `${autonomousResolutionRate}%`,
      total_resolution_rate: `${Math.round(((autonomousResolved + humanResolved) / totalTickets) * 1000) / 10}%`
    },

    escalation: {
      total_escalated: totalEscalated,
      escalation_rate: `${escalationRate}%`,
      by_trigger: escalationRateByTrigger,
      insight: getEscalationInsight(escalationRateByTrigger, totalTickets)
    },

    recontact: {
      recontact_count: recontacts,
      recontact_rate: `${recontactRate}%`,
      insight: recontactRate > 15
        ? 'Re-contact rate above 15% — tickets may be closing without genuine resolution.'
        : null
    },

    csat: {
      average: avgCsat,
      response_count: csatValues.length,
      response_rate: `${csatResponseRate}%`,
      below_threshold: belowThreshold,
      distribution: {
        5: csatValues.filter(s => s === 5).length,
        4: csatValues.filter(s => s === 4).length,
        3: csatValues.filter(s => s === 3).length,
        2: csatValues.filter(s => s === 2).length,
        1: csatValues.filter(s => s === 1).length
      }
    },

    response_time: {
      average_ms: avgResponseTime,
      average_seconds: avgResponseTimeSeconds,
      within_60s: responseTimes.filter(t => t <= 60000).length,
      within_60s_rate: responseTimes.length > 0
        ? `${Math.round((responseTimes.filter(t => t <= 60000).length / responseTimes.length) * 1000) / 10}%`
        : null
    },

    knowledge_base: {
      gap_count: kbGapCount,
      top_gaps: topGaps,
      insight: kbGapCount > 20
        ? 'High KB gap count — consider a focused content sprint to cover the top unanswered topics.'
        : null
    },

    timestamp: new Date().toISOString()
  };

  process.stdout.write(JSON.stringify(report));
}

function getEscalationInsight(byTrigger, totalTickets) {
  const confidenceRate = byTrigger.confidence?.rate || 0;
  const requestRate = byTrigger.request?.rate || 0;
  const sentimentRate = byTrigger.sentiment?.rate || 0;

  if (confidenceRate > 15) {
    return `${confidenceRate}% of tickets escalate due to low confidence — this is a knowledge base coverage problem. Review KB gaps and add content for the most common unanswered topics.`;
  }
  if (requestRate > 10) {
    return `${requestRate}% of customers ask for a human — this may indicate a trust problem with automated responses. Review autonomous response quality.`;
  }
  if (sentimentRate > 5) {
    return `${sentimentRate}% of tickets escalate due to sentiment — Vera may be missing frustration signals or failing to acknowledge them early enough.`;
  }
  return null;
}

function groupAndCount(items) {
  const counts = {};
  for (const item of items) {
    counts[item] = (counts[item] || 0) + 1;
  }
  return Object.entries(counts)
    .map(([topic, count]) => ({ topic, count }))
    .sort((a, b) => b.count - a.count);
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
