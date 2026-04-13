#!/usr/bin/env node
/**
 * lens-activation-check.js
 * Requirements 1-3: Validate vertical configuration and source hierarchies.
 */

async function main() {
  const input = await readStdin();
  const checks = [];

  const verticals = input?.verticals || {};
  const verticalNames = Object.keys(verticals);

  if (verticalNames.length === 0) {
    checks.push({
      check: 'verticals',
      pass: false,
      severity: 'blocker',
      reason: 'No research verticals configured. Lens needs at least one vertical with a source hierarchy before it can research.',
      remediation: 'Configure verticals during setup: financial, tech, academic, legal, competitive, or custom.'
    });
  } else {
    for (const name of verticalNames) {
      const v = verticals[name];
      const hasPrimary = v.primary && v.primary.length > 0;
      const hasSecondary = v.secondary && v.secondary.length > 0;
      if (!hasPrimary) {
        checks.push({
          check: `vertical_${name}`,
          pass: false,
          severity: 'blocker',
          reason: `Vertical "${name}" has no primary sources configured. Research without a primary source hierarchy is the condition that produced every documented failure.`,
          remediation: `Add primary sources for the ${name} vertical.`
        });
      } else {
        checks.push({
          check: `vertical_${name}`,
          pass: true,
          primary_count: v.primary.length,
          secondary_count: (v.secondary || []).length,
          community_count: (v.community_signal || []).length
        });
      }
    }
  }

  // Confidence thresholds
  const thresholds = input?.confidence_thresholds;
  if (!thresholds) {
    checks.push({
      check: 'confidence_thresholds',
      pass: true,
      note: 'Using defaults: Verified = 3+ independent primaries, Supported = 1 primary + 1 secondary.'
    });
  } else {
    checks.push({ check: 'confidence_thresholds', pass: true, custom: true });
  }

  // Freshness thresholds
  const freshness = input?.freshness_thresholds;
  if (!freshness) {
    checks.push({
      check: 'freshness_thresholds',
      pass: true,
      note: 'Using defaults: financial=90d, tech=180d, academic=365d, legal=30d, competitive=60d.'
    });
  } else {
    checks.push({ check: 'freshness_thresholds', pass: true, custom: true });
  }

  const blockers = checks.filter(c => !c.pass && c.severity === 'blocker');
  const result = {
    pass: blockers.length === 0,
    blockers,
    warnings: checks.filter(c => !c.pass && c.severity === 'warning'),
    checks,
    configured_verticals: verticalNames,
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
