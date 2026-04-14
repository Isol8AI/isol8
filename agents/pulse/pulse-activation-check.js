#!/usr/bin/env node
/**
 * pulse-activation-check.js
 * Requirements 1, 3: Validate brand voice doc and platform connections.
 *
 * Deterministic. Zero LLM.
 */

const REQUIRED_VOICE_SECTIONS = [
  'adjectives', 'on_off_brand_pairs', 'tone_scales',
  'anti_patterns', 'banned_phrases', 'terminology', 'audience_profiles'
];

async function main() {
  const input = await readStdin();
  const checks = [];

  // Brand voice document
  const voiceDoc = input?.brand_voice;
  if (!voiceDoc) {
    checks.push({
      check: 'brand_voice',
      pass: false,
      severity: 'blocker',
      reason: 'No brand voice document configured. Pulse cannot generate content without a codified brand voice — without it, output defaults to the statistical center of the internet ("corporate beige").',
      remediation: 'Run the brand voice building session during setup.'
    });
  } else {
    const missing = REQUIRED_VOICE_SECTIONS.filter(s => !voiceDoc[s] || (Array.isArray(voiceDoc[s]) && voiceDoc[s].length === 0));
    if (missing.length > 0) {
      checks.push({
        check: 'brand_voice',
        pass: false,
        severity: 'blocker',
        reason: `Brand voice document incomplete. Missing sections: ${missing.join(', ')}`,
        remediation: 'Complete the brand voice document with all required sections.'
      });
    } else {
      checks.push({ check: 'brand_voice', pass: true, sections: REQUIRED_VOICE_SECTIONS.length });
    }
  }

  // Social scheduling connection
  const social = input?.social_connection;
  if (!social || !social.connected) {
    checks.push({
      check: 'social_scheduling',
      pass: false,
      severity: 'warning',
      reason: 'No social scheduling platform connected. Content drafts will be generated but cannot be scheduled.',
      remediation: 'Connect adaptlypost, postiz, or post-bridge-social-manager.'
    });
  } else {
    checks.push({ check: 'social_scheduling', pass: true, platform: social.platform, draft_mode: social.draft_mode });
  }

  // Email platform
  const email = input?.email_connection;
  if (!email || !email.connected) {
    checks.push({
      check: 'email_platform',
      pass: false,
      severity: 'warning',
      reason: 'No email platform connected. Email operations will be limited.',
      remediation: 'Connect Mailchimp, Resend, or Postmark via direct API.'
    });
  } else {
    checks.push({ check: 'email_platform', pass: true, platform: email.platform });
  }

  // GEO query set
  const geoQueries = input?.geo_queries;
  if (!geoQueries || geoQueries.length === 0) {
    checks.push({
      check: 'geo_queries',
      pass: false,
      severity: 'warning',
      reason: 'No GEO query set configured. Share of Model tracking cannot run.',
      remediation: 'Configure the queries your customers use when researching your category.'
    });
  } else {
    checks.push({ check: 'geo_queries', pass: true, query_count: geoQueries.length });
  }

  // Competitor list
  const competitors = input?.competitors;
  if (!competitors || competitors.length === 0) {
    checks.push({
      check: 'competitors',
      pass: false,
      severity: 'warning',
      reason: 'No competitors configured. Competitive intelligence monitoring will be limited.',
      remediation: 'Add competitor domains and names during setup.'
    });
  } else {
    checks.push({ check: 'competitors', pass: true, count: competitors.length });
  }

  const blockers = checks.filter(c => !c.pass && c.severity === 'blocker');
  const result = {
    pass: blockers.length === 0,
    blockers,
    warnings: checks.filter(c => !c.pass && c.severity === 'warning'),
    checks,
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
