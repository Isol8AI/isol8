#!/usr/bin/env node
/**
 * pulse-geo-checker.js
 * Requirements 10, 11: GEO structural validation + platform-specific checks.
 *
 * Deterministic structural checks (~80%). Zero LLM.
 */

function checkGeoStructure(text, targetPlatform, metadata) {
  const checks = [];
  const words = text.split(/\s+/);
  const wordCount = words.length;

  // Check 1: BLUF — direct answer in first 40-60 words
  const first60Words = words.slice(0, 60).join(' ');
  const hasQuestion = first60Words.includes('?');
  const hasDefinitiveStatement = /\b(is|are|means|provides|enables|allows)\b/i.test(first60Words);
  checks.push({
    element: 'bluf',
    pass: hasDefinitiveStatement && !hasQuestion,
    detail: hasDefinitiveStatement
      ? 'Opening contains a definitive statement within 60 words.'
      : 'Opening lacks a direct answer. 44% of ChatGPT citations come from the first 30% of content — lead with the answer.',
    needs_llm_semantic: !hasDefinitiveStatement // Flag for LLM to check if BLUF actually answers the query
  });

  // Check 2: Statistic density — one stat with source every 150-200 words
  const statPattern = /\d+[\.,]?\d*\s*(%|percent|x|times|million|billion|thousand)/gi;
  const stats = text.match(statPattern) || [];
  const expectedStats = Math.floor(wordCount / 175);
  const hasAdequateStats = stats.length >= expectedStats;
  checks.push({
    element: 'statistic_density',
    pass: hasAdequateStats,
    found: stats.length,
    expected: expectedStats,
    detail: hasAdequateStats
      ? `${stats.length} statistics found (${expectedStats} expected for ${wordCount} words).`
      : `Only ${stats.length} statistics — need at least ${expectedStats} for ${wordCount} words. Stats with citations improve AI citation probability 30-40%.`
  });

  // Check 3: Source citations present
  const citationPatterns = /according to|research from|study by|data from|source:|per |found that|reported|published in/gi;
  const citations = text.match(citationPatterns) || [];
  checks.push({
    element: 'source_citations',
    pass: citations.length >= Math.max(1, Math.floor(stats.length * 0.5)),
    found: citations.length,
    detail: citations.length > 0
      ? `${citations.length} source citations found.`
      : 'No source citations detected. Citing sources improves AI citation probability significantly.'
  });

  // Check 4: Definitive language vs hedge words
  const hedgeWords = /\b(might|maybe|perhaps|possibly|could be|some people|it depends|arguably|in some cases)\b/gi;
  const hedges = text.match(hedgeWords) || [];
  const definitiveWords = /\b(is|are|means|requires|provides|ensures|produces|creates|drives|delivers)\b/gi;
  const definitives = text.match(definitiveWords) || [];
  const hedgeRatio = hedges.length / Math.max(1, hedges.length + definitives.length);
  checks.push({
    element: 'definitive_language',
    pass: hedgeRatio < 0.3,
    hedge_count: hedges.length,
    definitive_count: definitives.length,
    ratio: Math.round(hedgeRatio * 100),
    detail: hedgeRatio < 0.3
      ? 'Good definitive-to-hedge ratio.'
      : `${hedges.length} hedge words detected. Cited passages are 2x more likely to use definitive language.`
  });

  // Check 5: FAQ section present
  const hasFaq = /\b(faq|frequently asked|common questions|q&a|q:|question:)/gi.test(text);
  const hasQaPairs = (text.match(/\?\s*\n/g) || []).length >= 2;
  checks.push({
    element: 'faq_section',
    pass: hasFaq || hasQaPairs,
    detail: (hasFaq || hasQaPairs)
      ? 'FAQ/Q&A section detected.'
      : 'No FAQ section found. Q&A pairs matching natural queries are highly extractable by AI systems.'
  });

  // Check 6: Comparative/structured data
  const hasTable = /\|.*\|.*\|/m.test(text) || /<table/i.test(text);
  const hasComparisonWords = /\b(vs|versus|compared to|comparison|better than|worse than|alternative)\b/gi.test(text);
  checks.push({
    element: 'structured_data',
    pass: hasTable || !hasComparisonWords, // Only flag if content IS comparative but lacks tables
    detail: hasTable
      ? 'Structured table detected.'
      : hasComparisonWords
        ? 'Content contains comparisons but no structured table. Tables are easier for AI to parse and cite accurately.'
        : 'No comparison context — table not required.'
  });

  // Platform-specific checks (Req 11)
  const platformChecks = [];
  if (targetPlatform === 'chatgpt' || !targetPlatform) {
    platformChecks.push({
      platform: 'chatgpt',
      check: 'word_count',
      pass: wordCount >= 1500,
      detail: wordCount >= 1500
        ? `${wordCount} words — adequate for ChatGPT\'s preference for encyclopedic coverage.`
        : `${wordCount} words — ChatGPT favors comprehensive long-form (1500+). Consider expanding.`
    });
  }
  if (targetPlatform === 'perplexity' || !targetPlatform) {
    const publishDate = metadata?.published_date ? new Date(metadata.published_date) : null;
    const ageInDays = publishDate ? (Date.now() - publishDate.getTime()) / (1000 * 60 * 60 * 24) : null;
    platformChecks.push({
      platform: 'perplexity',
      check: 'recency',
      pass: ageInDays === null || ageInDays <= 30,
      detail: ageInDays === null
        ? 'New content — Perplexity rewards recency.'
        : ageInDays <= 30
          ? `${Math.round(ageInDays)} days old — within Perplexity\'s recency window.`
          : `${Math.round(ageInDays)} days old — Perplexity rewards recent content. Consider updating.`
    });
  }

  const passedChecks = checks.filter(c => c.pass).length;
  const totalChecks = checks.length;
  const geoScore = Math.round((passedChecks / totalChecks) * 100);

  return {
    geo_score: geoScore,
    checks,
    platform_checks: platformChecks,
    passed: passedChecks,
    total: totalChecks,
    word_count: wordCount,
    needs_llm_semantic: checks.some(c => c.needs_llm_semantic),
    timestamp: new Date().toISOString()
  };
}

async function main() {
  const input = await readStdin();
  if (!input) {
    process.stderr.write('No input provided');
    process.exit(1);
  }

  const text = input.text || input.draft?.body || '';
  const platform = input.target_platform || null;
  const metadata = input.metadata || {};

  const result = checkGeoStructure(text, platform, metadata);
  process.stdout.write(JSON.stringify(result));
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

module.exports = { checkGeoStructure };

if (require.main === module) {
  main().catch(err => {
    process.stderr.write(err.message);
    process.exit(1);
  });
}
