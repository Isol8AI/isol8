#!/usr/bin/env node
/**
 * vera-escalation-health.js
 * Requirements 3, 4, 5: Test and monitor escalation path health.
 *
 * Runs on 30-minute cron during business hours.
 * Tests each configured channel via API health checks.
 * Deterministic. Zero LLM.
 */

function checkChannelHealth(channel, testResults) {
  const result = {
    channel: channel.type,
    destination: channel.destination,
    status: 'unknown',
    checked_at: new Date().toISOString()
  };

  const testResult = testResults?.[channel.type];

  if (!testResult) {
    result.status = 'unreachable';
    result.reason = `No test result available for ${channel.type}. Channel may not be connected.`;
    return result;
  }

  if (testResult.success) {
    if (testResult.latency_ms && testResult.latency_ms > 5000) {
      result.status = 'degraded';
      result.reason = `Channel responding but slow (${testResult.latency_ms}ms). May cause delays in escalation delivery.`;
    } else {
      result.status = 'active';
    }
  } else {
    result.status = 'unreachable';
    result.reason = testResult.error || `Channel test failed for ${channel.type}.`;
    result.error_detail = testResult.error_detail || null;
  }

  return result;
}

function getOverallStatus(channelResults) {
  const statuses = channelResults.map(c => c.status);

  if (statuses.every(s => s === 'active')) return 'green';
  if (statuses.some(s => s === 'unreachable')) {
    // Check if primary is down
    const primaryDown = channelResults[0]?.status === 'unreachable';
    if (primaryDown) return 'red';
    return 'yellow';
  }
  if (statuses.some(s => s === 'degraded')) return 'yellow';
  return 'red';
}

function getStatusEmoji(status) {
  return { green: '🟢', yellow: '🟡', red: '🔴' }[status] || '⚪';
}

async function main() {
  const input = await readStdin();
  if (!input) {
    process.stderr.write('No input provided');
    process.exit(1);
  }

  const escalationPath = input.escalation_path || {};
  const testResults = input.test_results || {};
  const isBusinessHours = input.is_business_hours || false;

  // Build channel list from escalation path config
  const channels = [];
  if (escalationPath.slack_channel) {
    channels.push({ type: 'slack', destination: escalationPath.slack_channel, primary: true });
  }
  if (escalationPath.email_inbox) {
    channels.push({ type: 'email', destination: escalationPath.email_inbox, primary: !escalationPath.slack_channel });
  }
  if (escalationPath.phone_number) {
    channels.push({ type: 'phone', destination: escalationPath.phone_number, primary: false });
  }

  if (channels.length === 0) {
    process.stdout.write(JSON.stringify({
      overall_status: 'red',
      emoji: '🔴',
      alert: true,
      reason: 'No escalation channels configured. Vera has no human lifeline.',
      channels: [],
      timestamp: new Date().toISOString()
    }));
    process.exit(1);
    return;
  }

  const channelResults = channels.map(ch => checkChannelHealth(ch, testResults));
  const overallStatus = getOverallStatus(channelResults);
  const emoji = getStatusEmoji(overallStatus);

  const result = {
    overall_status: overallStatus,
    emoji,
    alert: overallStatus === 'red' || (overallStatus === 'yellow' && isBusinessHours),
    channels: channelResults,
    is_business_hours: isBusinessHours,
    summary: `Escalation health: ${emoji} ${overallStatus.toUpperCase()}. ${channelResults.filter(c => c.status === 'active').length}/${channelResults.length} channels active.`,
    unreachable: channelResults.filter(c => c.status === 'unreachable'),
    degraded: channelResults.filter(c => c.status === 'degraded'),
    timestamp: new Date().toISOString()
  };

  process.stdout.write(JSON.stringify(result));
  process.exit(overallStatus === 'red' ? 1 : 0);
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
