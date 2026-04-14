#!/usr/bin/env node
/**
 * thread-triage-scorer.js
 * Requirements 3, 4, 26, 27: Composite triage scoring with adaptive calibration.
 *
 * Deterministic scoring. Weights adjust from capability-evolver feedback.
 */

const DEFAULT_WEIGHTS = {
  wait_time: 0.25,
  relationship_tier: 0.30,
  urgency_signals: 0.25,
  reply_context: 0.20
};

const RELATIONSHIP_TIERS = {
  established_client: 100,
  active_vendor: 80,
  internal_team: 70,
  known_contact: 50,
  cold_contact: 20,
  automated: 5
};

const URGENCY_KEYWORDS = [
  'urgent', 'asap', 'immediately', 'critical', 'deadline', 'expires',
  'end of day', 'eod', 'by cob', 'time-sensitive', 'action required',
  'overdue', 'past due', 'final notice', 'last chance'
];

function scoreMessage(message, config) {
  const weights = config.weights || DEFAULT_WEIGHTS;
  const tiers = config.relationship_tiers || RELATIONSHIP_TIERS;
  const now = Date.now();

  // Dimension 1: Wait time (exponential — 48h scores much higher than 4h)
  const messageTime = new Date(message.timestamp).getTime();
  const hoursWaiting = (now - messageTime) / (1000 * 60 * 60);
  const waitScore = Math.min(100, Math.pow(hoursWaiting / 2, 1.3)); // Exponential curve

  // Dimension 2: Relationship tier
  const senderTier = message.sender_tier || message.relationship_tier || 'known_contact';
  const tierScore = tiers[senderTier] || tiers.known_contact;

  // Dimension 3: Urgency signals in content
  const lower = (message.preview || message.subject || message.text || '').toLowerCase();
  const urgencyHits = URGENCY_KEYWORDS.filter(kw => lower.includes(kw)).length;
  const urgencyScore = Math.min(100, urgencyHits * 30);

  // Dimension 4: Reply context (response to user's outbound = higher)
  const isReply = message.is_reply_to_user || false;
  const replyScore = isReply ? 80 : 20;

  // Composite score
  const composite = Math.round(
    waitScore * weights.wait_time +
    tierScore * weights.relationship_tier +
    urgencyScore * weights.urgency_signals +
    replyScore * weights.reply_context
  );

  // Time-sensitivity boost (Req 26)
  let timeSensitivityBoost = 0;
  const today = new Date().toISOString().split('T')[0];
  const todayWords = new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' });

  if (lower.includes('today') || lower.includes('expires today') ||
      lower.includes(today) || lower.includes(todayWords.toLowerCase()) ||
      lower.includes('end of day') || lower.includes('by cob')) {
    timeSensitivityBoost = 40;
  } else if (lower.includes('tomorrow') || lower.includes('by end of week')) {
    timeSensitivityBoost = 20;
  }

  // Calendar boost — if message mentions a meeting happening today
  if (message.calendar_match_today) {
    timeSensitivityBoost = Math.max(timeSensitivityBoost, 35);
  }

  const finalScore = Math.min(100, composite + timeSensitivityBoost);

  return {
    message_id: message.id,
    sender: message.sender,
    channel: message.channel,
    composite_score: composite,
    time_sensitivity_boost: timeSensitivityBoost,
    final_score: finalScore,
    breakdown: {
      wait_time: { raw: Math.round(waitScore), weight: weights.wait_time, hours: Math.round(hoursWaiting) },
      relationship: { raw: tierScore, weight: weights.relationship_tier, tier: senderTier },
      urgency: { raw: urgencyScore, weight: weights.urgency_signals, keywords_found: urgencyHits },
      reply_context: { raw: replyScore, weight: weights.reply_context, is_reply: isReply }
    },
    timestamp: new Date().toISOString()
  };
}

async function main() {
  const input = await readStdin();
  if (!input) { process.stderr.write('No input'); process.exit(1); }

  const messages = input.messages || [];
  const config = {
    weights: input.weights || DEFAULT_WEIGHTS,
    relationship_tiers: input.relationship_tiers || RELATIONSHIP_TIERS
  };

  const scored = messages.map(m => scoreMessage(m, config));
  const ranked = scored.sort((a, b) => b.final_score - a.final_score);

  const result = {
    ranked,
    total: ranked.length,
    top_3: ranked.slice(0, 3).map(r => ({ sender: r.sender, channel: r.channel, score: r.final_score })),
    time_sensitive_count: ranked.filter(r => r.time_sensitivity_boost > 0).length,
    weights_used: config.weights,
    timestamp: new Date().toISOString()
  };

  process.stdout.write(JSON.stringify(result));
}

function readStdin() {
  return new Promise((resolve) => {
    let data = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', chunk => data += chunk);
    process.stdin.on('end', () => { try { resolve(JSON.parse(data)); } catch { resolve(null); } });
    if (process.stdin.isTTY) resolve(null);
  });
}

module.exports = { scoreMessage, DEFAULT_WEIGHTS, RELATIONSHIP_TIERS };

if (require.main === module) { main().catch(err => { process.stderr.write(err.message); process.exit(1); }); }
