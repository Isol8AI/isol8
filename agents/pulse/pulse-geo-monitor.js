#!/usr/bin/env node
/**
 * pulse-geo-monitor.js
 * Requirements 24, 39: Share of Model tracking. Deterministic counting/trending.
 */

async function main() {
  const input = await readStdin();
  if (!input) { process.stderr.write('No input'); process.exit(1); }

  const queryResults = input.query_results || [];
  const brandName = (input.brand_name || '').toLowerCase();
  const priorWeeks = input.prior_weeks || [];

  let cited = 0;
  let total = queryResults.length;
  const details = [];

  for (const qr of queryResults) {
    const isCited = (qr.response || '').toLowerCase().includes(brandName);
    if (isCited) cited++;
    details.push({
      query: qr.query,
      platform: qr.platform,
      brand_cited: isCited,
      sources_cited: qr.sources_cited || [],
      competitors_cited: (qr.sources_cited || []).filter(s =>
        (input.competitors || []).some(c => s.toLowerCase().includes(c.toLowerCase()))
      )
    });
  }

  const shareOfModel = total > 0 ? Math.round((cited / total) * 1000) / 10 : 0;
  const priorShare = priorWeeks[0]?.share_of_model;
  const trend = priorShare !== undefined ? Math.round((shareOfModel - priorShare) * 10) / 10 : null;

  const result = {
    share_of_model: shareOfModel,
    cited_count: cited,
    total_queries: total,
    trend_vs_prior: trend,
    trend_direction: trend > 0 ? 'improving' : trend < 0 ? 'declining' : 'stable',
    significant_change: Math.abs(trend || 0) >= 5,
    details,
    not_cited_queries: details.filter(d => !d.brand_cited).map(d => d.query),
    competitor_presence: summarizeCompetitors(details),
    timestamp: new Date().toISOString()
  };

  process.stdout.write(JSON.stringify(result));
}

function summarizeCompetitors(details) {
  const counts = {};
  for (const d of details) {
    for (const c of d.competitors_cited) {
      counts[c] = (counts[c] || 0) + 1;
    }
  }
  return Object.entries(counts)
    .map(([name, count]) => ({ competitor: name, cited_in: count, pct: Math.round((count / details.length) * 100) }))
    .sort((a, b) => b.cited_in - a.cited_in);
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
