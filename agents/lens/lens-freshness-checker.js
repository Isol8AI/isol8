#!/usr/bin/env node
/**
 * lens-freshness-checker.js
 * Requirement 31: Date every source, flag staleness per vertical threshold.
 *
 * Deterministic date math. Configurable thresholds per vertical.
 */

const DEFAULT_THRESHOLDS = {
  financial: { primary: 90, secondary: 30, community: 7 },
  technology: { primary: 180, secondary: 60, community: 30 },
  academic: { primary: 365, secondary: 180, community: 90 },
  legal: { primary: 30, secondary: 90, community: 30 },
  competitive: { primary: 60, secondary: 30, community: 14 }
};

async function main() {
  const input = await readStdin();
  if (!input) { process.stderr.write('No input'); process.exit(1); }

  const sources = input.sources || [];
  const vertical = input.vertical || 'technology';
  const customThresholds = input.freshness_thresholds || {};
  const thresholds = { ...DEFAULT_THRESHOLDS[vertical], ...(customThresholds[vertical] || {}) };
  const now = Date.now();

  const checked = sources.map(source => {
    const sourceDate = new Date(source.date || source.published_date);
    const ageDays = Math.floor((now - sourceDate.getTime()) / (1000 * 60 * 60 * 24));
    const tier = source.tier || 'secondary';
    const threshold = thresholds[tier] || thresholds.secondary || 90;
    const isStale = ageDays > threshold;

    return {
      url: source.url,
      title: source.title,
      tier,
      date: source.date,
      age_days: ageDays,
      threshold_days: threshold,
      is_stale: isStale,
      staleness_severity: isStale
        ? (ageDays > threshold * 2 ? 'critical' : 'warning')
        : 'fresh',
      flag: isStale
        ? `Source is ${ageDays} days old. ${vertical} ${tier} staleness threshold is ${threshold} days. Verify current accuracy.`
        : null
    };
  });

  const stale = checked.filter(c => c.is_stale);

  const result = {
    checked,
    stale_count: stale.length,
    fresh_count: checked.length - stale.length,
    critical_count: stale.filter(s => s.staleness_severity === 'critical').length,
    vertical,
    thresholds_used: thresholds,
    custom_thresholds: Object.keys(customThresholds).length > 0,
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
