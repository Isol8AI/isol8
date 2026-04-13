#!/usr/bin/env node
/**
 * thread-preference-learner.js
 * Requirements 13, 14: Behavioral channel preference model from response latency.
 *
 * Deterministic math from timestamps. Runs nightly on cron.
 */

async function main() {
  const input = await readStdin();
  if (!input) { process.stderr.write('No input'); process.exit(1); }

  const contacts = input.contacts || {};
  const messageHistory = input.message_history || [];
  const existingPreferences = input.existing_preferences || {};

  const updated = {};

  // Group messages by contact
  const byContact = {};
  for (const msg of messageHistory) {
    const contactId = msg.contact_id || msg.sender_id || msg.recipient_id;
    if (!contactId) continue;
    if (!byContact[contactId]) byContact[contactId] = [];
    byContact[contactId].push(msg);
  }

  for (const [contactId, messages] of Object.entries(byContact)) {
    const channelStats = {};

    // Sort by timestamp
    const sorted = messages.sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));

    // Calculate response latency per channel
    for (let i = 0; i < sorted.length - 1; i++) {
      const outbound = sorted[i];
      const next = sorted[i + 1];

      // Find response pairs: user sends, contact responds
      if (outbound.direction === 'outbound' && next.direction === 'inbound' &&
          next.contact_id === outbound.contact_id) {
        const channel = next.channel;
        const latencyMs = new Date(next.timestamp) - new Date(outbound.timestamp);
        const latencyMinutes = latencyMs / (1000 * 60);

        // Skip unreasonably long gaps (> 30 days = probably not a direct response)
        if (latencyMinutes > 43200) continue;

        if (!channelStats[channel]) channelStats[channel] = { latencies: [], initiations: 0, substantive: 0 };
        channelStats[channel].latencies.push(latencyMinutes);
      }

      // Track which channel contact initiates on
      if (sorted[i].direction === 'inbound') {
        const ch = sorted[i].channel;
        if (!channelStats[ch]) channelStats[ch] = { latencies: [], initiations: 0, substantive: 0 };
        channelStats[ch].initiations++;

        // Track substantive messages (longer content = more substantive)
        const len = (sorted[i].text || sorted[i].preview || '').length;
        if (len > 100) channelStats[ch].substantive++;
      }
    }

    // Compute preference scores
    const preferences = {};
    for (const [channel, stats] of Object.entries(channelStats)) {
      const avgLatency = stats.latencies.length > 0
        ? stats.latencies.reduce((a, b) => a + b, 0) / stats.latencies.length
        : null;
      const medianLatency = stats.latencies.length > 0
        ? stats.latencies.sort((a, b) => a - b)[Math.floor(stats.latencies.length / 2)]
        : null;

      // Score: lower latency = higher score, with bonuses for initiation and substance
      const latencyScore = avgLatency ? Math.max(0, 100 - (avgLatency / 60)) : 0; // hours → score
      const initiationBonus = Math.min(20, stats.initiations * 5);
      const substanceBonus = Math.min(10, stats.substantive * 3);
      const totalScore = Math.round(latencyScore + initiationBonus + substanceBonus);

      preferences[channel] = {
        score: totalScore,
        avg_response_minutes: avgLatency ? Math.round(avgLatency) : null,
        median_response_minutes: medianLatency ? Math.round(medianLatency) : null,
        interactions: stats.latencies.length + stats.initiations,
        initiations: stats.initiations,
        substantive_messages: stats.substantive
      };
    }

    // Rank channels
    const ranked = Object.entries(preferences)
      .sort((a, b) => b[1].score - a[1].score)
      .map(([ch, data], i) => ({ channel: ch, rank: i + 1, ...data }));

    updated[contactId] = {
      preferences,
      ranked,
      best_channel: ranked[0]?.channel || null,
      data_sufficient: ranked.length > 0 && ranked[0]?.interactions >= 3,
      last_updated: new Date().toISOString()
    };
  }

  const result = {
    contacts_updated: Object.keys(updated).length,
    preferences: updated,
    contacts_with_sufficient_data: Object.values(updated).filter(u => u.data_sufficient).length,
    contacts_needing_more_data: Object.values(updated).filter(u => !u.data_sufficient).length,
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

if (require.main === module) { main().catch(err => { process.stderr.write(err.message); process.exit(1); }); }
