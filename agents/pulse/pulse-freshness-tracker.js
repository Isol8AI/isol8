#!/usr/bin/env node
/**
 * pulse-freshness-tracker.js
 * Requirements 25, 37: Content freshness monitoring. Deterministic date math.
 */

const STALE_THRESHOLDS = { high_priority: 90, review: 180, archive: 365 };

async function main() {
  const input = await readStdin();
  if (!input) { process.stderr.write('No input'); process.exit(1); }

  const content = input.content_archive || [];
  const citationData = input.citation_data || {};
  const now = Date.now();
  const currentYear = new Date().getFullYear();

  const flagged = content.map(piece => {
    const published = new Date(piece.published_date || piece.created_date);
    const lastUpdated = new Date(piece.last_updated || piece.published_date);
    const ageDays = Math.floor((now - published.getTime()) / (1000 * 60 * 60 * 24));
    const daysSinceUpdate = Math.floor((now - lastUpdated.getTime()) / (1000 * 60 * 60 * 24));

    // Check for stale year references in text
    const yearPattern = /\b(20\d{2})\b/g;
    const years = [];
    let match;
    const text = piece.text || piece.body || '';
    while ((match = yearPattern.exec(text)) !== null) years.push(parseInt(match[1]));
    const staleYears = years.filter(y => y < currentYear - 1);

    // Citation status
    const isCited = citationData[piece.id]?.currently_cited || false;
    const wasCited = citationData[piece.id]?.previously_cited || false;
    const citationValue = isCited ? 3 : wasCited ? 2 : 1;

    // Staleness score = age weight × inverse citation protection
    const stalenessScore = Math.round((daysSinceUpdate / 30) * citationValue);

    let severity = 'current';
    if (daysSinceUpdate > STALE_THRESHOLDS.archive) severity = 'archive';
    else if (daysSinceUpdate > STALE_THRESHOLDS.review) severity = 'review';
    else if (daysSinceUpdate > STALE_THRESHOLDS.high_priority && isCited) severity = 'high_priority_refresh';
    else if (staleYears.length > 0) severity = 'stale_statistics';

    return {
      id: piece.id,
      title: piece.title,
      url: piece.url,
      age_days: ageDays,
      days_since_update: daysSinceUpdate,
      stale_years: staleYears,
      is_cited: isCited,
      was_cited: wasCited,
      citation_value: citationValue,
      staleness_score: stalenessScore,
      severity
    };
  }).filter(p => p.severity !== 'current');

  // Sort by staleness score descending (highest priority first)
  const refreshQueue = flagged.sort((a, b) => b.staleness_score - a.staleness_score).slice(0, 10);

  const result = {
    refresh_queue: refreshQueue,
    total_content: content.length,
    flagged_count: flagged.length,
    high_priority: flagged.filter(f => f.severity === 'high_priority_refresh').length,
    stale_stats: flagged.filter(f => f.severity === 'stale_statistics').length,
    archive_candidates: flagged.filter(f => f.severity === 'archive').length,
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
