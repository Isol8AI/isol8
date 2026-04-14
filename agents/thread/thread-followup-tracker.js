#!/usr/bin/env node
/**
 * thread-followup-tracker.js
 * Requirements 21, 22: Track unanswered outbound, suggest follow-ups with channel alternatives.
 *
 * Deterministic timestamp comparison. Adaptive thresholds per contact.
 */

const DEFAULT_THRESHOLDS = {
  established_client: 2,   // days
  active_vendor: 3,
  internal_team: 1,
  known_contact: 3,
  cold_contact: 5,
  automated: null           // never follow up on automated
};

async function main() {
  const input = await readStdin();
  if (!input) { process.stderr.write('No input'); process.exit(1); }

  const outboundMessages = input.outbound_messages || [];
  const inboundMessages = input.inbound_messages || [];
  const contactPreferences = input.contact_preferences || {};
  const customThresholds = input.custom_thresholds || {};
  const now = Date.now();

  // Build set of answered messages
  const answeredOutboundIds = new Set();
  for (const inbound of inboundMessages) {
    if (inbound.in_reply_to) answeredOutboundIds.add(inbound.in_reply_to);
    // Also match by contact + time proximity (within 48h of outbound = likely response)
    for (const outbound of outboundMessages) {
      if (outbound.contact_id === inbound.contact_id &&
          !answeredOutboundIds.has(outbound.id)) {
        const timeDiff = new Date(inbound.timestamp) - new Date(outbound.timestamp);
        if (timeDiff > 0 && timeDiff < 48 * 60 * 60 * 1000) {
          answeredOutboundIds.add(outbound.id);
        }
      }
    }
  }

  const unanswered = outboundMessages
    .filter(m => !answeredOutboundIds.has(m.id))
    .map(m => {
      const daysWaiting = (now - new Date(m.timestamp).getTime()) / (1000 * 60 * 60 * 24);
      const tier = m.relationship_tier || 'known_contact';

      // Use custom threshold if set for this contact, otherwise default by tier
      const contactId = m.contact_id || m.contact_email;
      const threshold = customThresholds[contactId]?.days ||
                        DEFAULT_THRESHOLDS[tier];

      if (threshold === null) return null; // Don't track automated

      // Adapt threshold based on contact's historical response time
      const pref = contactPreferences[contactId];
      const avgResponseDays = pref?.avg_response_minutes
        ? pref.avg_response_minutes / (60 * 24)
        : null;
      const adaptiveThreshold = avgResponseDays
        ? Math.max(threshold, Math.ceil(avgResponseDays * 1.5)) // 1.5x their average
        : threshold;

      const isOverdue = daysWaiting >= adaptiveThreshold;
      const isDoubleOverdue = daysWaiting >= adaptiveThreshold * 2;

      return {
        message_id: m.id,
        contact: m.contact_name || m.contact_email,
        contact_id: contactId,
        channel: m.channel,
        subject: m.subject || m.preview,
        sent_date: m.timestamp,
        days_waiting: Math.round(daysWaiting * 10) / 10,
        threshold_days: adaptiveThreshold,
        is_overdue: isOverdue,
        suggest_channel_switch: isDoubleOverdue,
        alternative_channel: isDoubleOverdue
          ? pref?.ranked?.[1]?.channel || null
          : null,
        suggestion: isOverdue
          ? isDoubleOverdue
            ? `You messaged ${m.contact_name} about "${m.subject || 'this'}" ${Math.round(daysWaiting)} days ago on ${m.channel}. No response. Want to try ${pref?.ranked?.[1]?.channel || 'a different channel'}?`
            : `You messaged ${m.contact_name} about "${m.subject || 'this'}" ${Math.round(daysWaiting)} days ago on ${m.channel}. No response. Want me to draft a follow-up?`
          : null
      };
    })
    .filter(Boolean);

  const overdue = unanswered.filter(u => u.is_overdue);

  const result = {
    unanswered: unanswered,
    overdue: overdue,
    overdue_count: overdue.length,
    channel_switch_suggestions: overdue.filter(u => u.suggest_channel_switch).length,
    total_tracked: outboundMessages.length,
    answered: answeredOutboundIds.size,
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
