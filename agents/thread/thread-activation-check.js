#!/usr/bin/env node
/**
 * thread-activation-check.js
 * Requirements 28, 29: Validate channel connections and minimum permissions.
 */

async function main() {
  const input = await readStdin();
  const checks = [];

  const channels = input?.connected_channels || [];

  if (channels.length === 0) {
    checks.push({
      check: 'channels',
      pass: false,
      severity: 'blocker',
      reason: 'No communication channels connected. Thread needs at least one channel to function.',
      remediation: 'Connect Gmail (gog), Slack, or any supported channel during setup.'
    });
  } else {
    for (const ch of channels) {
      const hasRead = ch.permissions?.includes('read');
      const hasSend = ch.permissions?.includes('send');
      const excessPermissions = ch.permissions?.filter(p => !['read', 'send'].includes(p));

      checks.push({
        check: `channel_${ch.name}`,
        pass: hasRead,
        has_read: hasRead,
        has_send: hasSend,
        excess_permissions: excessPermissions?.length > 0 ? excessPermissions : null,
        warning: excessPermissions?.length > 0
          ? `Channel ${ch.name} has permissions beyond minimum: ${excessPermissions.join(', ')}. Consider reducing to read + send only.`
          : null
      });
    }
  }

  // Email security layer
  const emailSecurity = input?.email_security;
  if (!emailSecurity || !emailSecurity.installed) {
    checks.push({
      check: 'email_security',
      pass: false,
      severity: 'blocker',
      reason: 'email-security skill not installed. Thread cannot process email without the sanitization layer — the EchoLeak vulnerability (CVE-2025-32711) delivered attacks through invisible HTML elements.',
      remediation: 'Install email-security before connecting any email channel — Thread must not read a raw email body.'
    });
  } else {
    checks.push({ check: 'email_security', pass: true });
  }

  // Auto-send configuration
  const autoSend = input?.auto_send_channels || [];
  const externalAutoSend = autoSend.filter(ch => ch.type === 'external');
  if (externalAutoSend.length > 0) {
    checks.push({
      check: 'auto_send_safety',
      pass: false,
      severity: 'blocker',
      reason: `Auto-send configured for external channels: ${externalAutoSend.map(c => c.name).join(', ')}. Thread never auto-sends to external contacts.`,
      remediation: 'Remove external channels from auto-send configuration. Only internal Slack channels qualify.'
    });
  }

  // History window
  const historyWindow = input?.history_window;
  if (!historyWindow) {
    checks.push({
      check: 'history_window',
      pass: true,
      note: 'Using default: last 100 messages per contact. Full history on explicit request only.'
    });
  }

  const blockers = checks.filter(c => !c.pass && c.severity === 'blocker');
  const result = {
    pass: blockers.length === 0,
    blockers,
    warnings: checks.filter(c => c.warning || (!c.pass && c.severity === 'warning')),
    checks,
    connected_channels: channels.map(c => c.name),
    timestamp: new Date().toISOString()
  };

  process.stdout.write(JSON.stringify(result));
  process.exit(blockers.length === 0 ? 0 : 1);
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
