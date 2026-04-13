#!/usr/bin/env node
/**
 * thread-contact-context.js
 * Requirement 20: Surface last contact, recent topic, follow-ups, best channel.
 *
 * Deterministic assembly from fast-io. summarize CLI for topic compression in pipeline.
 */

async function main() {
  const input = await readStdin();
  if (!input) { process.stderr.write('No input'); process.exit(1); }

  const contact = input.contact || {};
  const history = input.history || [];
  const preferences = input.preferences || {};
  const pendingFollowups = input.pending_followups || [];

  // Last communication
  const lastMessage = history.length > 0 ? history[history.length - 1] : null;
  const lastContact = lastMessage ? {
    date: lastMessage.timestamp,
    channel: lastMessage.channel,
    direction: lastMessage.direction,
    days_ago: Math.floor((Date.now() - new Date(lastMessage.timestamp).getTime()) / (1000 * 60 * 60 * 24))
  } : null;

  // Recent messages for topic extraction (summarize CLI handles in pipeline)
  const recentMessages = history.slice(-5).map(m => ({
    timestamp: m.timestamp,
    channel: m.channel,
    direction: m.direction,
    preview: (m.text || m.preview || '').substring(0, 200)
  }));

  // Pending follow-ups
  const followups = pendingFollowups.filter(f =>
    f.contact_id === contact.id || f.contact_email === contact.email
  ).map(f => ({
    sent_date: f.sent_date,
    channel: f.channel,
    subject: f.subject || f.preview,
    days_waiting: Math.floor((Date.now() - new Date(f.sent_date).getTime()) / (1000 * 60 * 60 * 24))
  }));

  // Best channel
  const channelRanking = preferences.ranked || [];
  const bestChannel = channelRanking[0] || null;

  // Communication frequency
  const last30Days = history.filter(m => {
    const age = (Date.now() - new Date(m.timestamp).getTime()) / (1000 * 60 * 60 * 24);
    return age <= 30;
  });
  const frequency = {
    messages_last_30d: last30Days.length,
    inbound: last30Days.filter(m => m.direction === 'inbound').length,
    outbound: last30Days.filter(m => m.direction === 'outbound').length,
    channels_used: [...new Set(last30Days.map(m => m.channel))]
  };

  const result = {
    contact: {
      name: contact.name,
      email: contact.email,
      organization: contact.organization,
      tier: contact.relationship_tier || 'known_contact'
    },
    last_contact: lastContact,
    recent_messages: recentMessages,
    pending_followups: followups,
    best_channel: bestChannel,
    communication_frequency: frequency,
    needs_topic_summary: recentMessages.length > 0,
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
