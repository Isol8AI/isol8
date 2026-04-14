#!/usr/bin/env node
/**
 * thread-channel-router.js
 * Requirements 12, 15, 16, 17, 18: Route outbound via preference model with safety gates.
 *
 * Deterministic routing. Agent loop for override learning.
 */

const CHANNEL_TONE_GUIDANCE = {
  slack: 'Concise, direct, no formal salutation. Often a single sentence or short paragraph. No subject line.',
  email: 'Complete message with subject line. Professional opening, appropriate sign-off. Full context — the recipient may not have Slack context.',
  whatsapp: 'Conversational and informal. Short messages. Emojis acceptable if the relationship warrants.',
  linkedin: 'Professionally warm. Slightly more formal than email. Reference shared context or connection.',
  sms: 'Short and direct. 1-2 sentences maximum. No formatting. The most interruptive channel — only for time-sensitive.'
};

function routeOutbound(contact, connectedChannels, autoSendChannels, userOverrides) {
  const preferences = contact.channel_preferences || {};
  const overrides = userOverrides || {};

  // Check if user has a manual override for this contact
  const contactOverride = overrides[contact.id] || overrides[contact.email];
  if (contactOverride) {
    return {
      channel: contactOverride.channel,
      reason: `User override: always use ${contactOverride.channel} for ${contact.name}.`,
      confidence: 'user_override',
      tone_guidance: CHANNEL_TONE_GUIDANCE[contactOverride.channel] || '',
      requires_confirmation: !isAutoSendEligible(contactOverride.channel, contact, autoSendChannels),
      is_external: contact.is_external !== false
    };
  }

  // Rank channels by preference score (response latency inverse)
  const ranked = Object.entries(preferences)
    .filter(([channel]) => connectedChannels.includes(channel))
    .sort((a, b) => b[1].score - a[1].score);

  if (ranked.length === 0) {
    // No preference data — new contact or insufficient history
    return {
      channel: null,
      reason: `No preference data for ${contact.name}. Ask user which channel to use.`,
      confidence: 'none',
      needs_agent_loop: true,
      agent_loop_context: `New contact or insufficient interaction history. Ask the user which channel to reach ${contact.name} on. Store the answer for future routing.`
    };
  }

  const bestChannel = ranked[0][0];
  const bestScore = ranked[0][1];
  const secondBest = ranked.length > 1 ? ranked[1] : null;

  // Confidence based on data points
  const dataPoints = bestScore.interactions || 0;
  const confidence = dataPoints >= 5 ? 'high' : dataPoints >= 3 ? 'medium' : 'low';

  return {
    channel: bestChannel,
    reason: confidence === 'high'
      ? `${contact.name} responds in ${bestScore.avg_response_minutes} min on ${bestChannel}.`
      : `${contact.name} has ${dataPoints} interactions on ${bestChannel}. Routing there, but confidence is ${confidence}.`,
    confidence,
    avg_response_minutes: bestScore.avg_response_minutes,
    alternative: secondBest ? { channel: secondBest[0], avg_response_minutes: secondBest[1].avg_response_minutes } : null,
    tone_guidance: CHANNEL_TONE_GUIDANCE[bestChannel] || '',
    requires_confirmation: !isAutoSendEligible(bestChannel, contact, autoSendChannels),
    is_external: contact.is_external !== false,
    data_points: dataPoints
  };
}

function isAutoSendEligible(channel, contact, autoSendChannels) {
  // Only internal Slack channels qualify for auto-send
  if (channel !== 'slack') return false;
  if (contact.is_external !== false) return false;
  return (autoSendChannels || []).some(ch =>
    ch.channel === channel && ch.type === 'internal'
  );
}

async function main() {
  const input = await readStdin();
  if (!input) { process.stderr.write('No input'); process.exit(1); }

  const result = routeOutbound(
    input.contact || {},
    input.connected_channels || [],
    input.auto_send_channels || [],
    input.user_overrides || {}
  );

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

module.exports = { routeOutbound, CHANNEL_TONE_GUIDANCE };

if (require.main === module) { main().catch(err => { process.stderr.write(err.message); process.exit(1); }); }
